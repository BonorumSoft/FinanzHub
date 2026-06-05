"""Notification-Engine: plant, rendert und versendet Benachrichtigungen.

Verwendet :class:`app.notifications.config` für das Template-Rendering und
:mod:`app.output.mail_service` für den Versand. Alle versendeten Mails
werden in ``notification_log`` protokolliert (append-only).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config_loader import MailConfig, NotificationsConfig
from app.data.db import execute
from app.logger import get_logger
from app.notifications.config import render
from app.output.mail_service import MailResult, MailService

logger = get_logger(__name__)


def _utcnow() -> datetime:
    """Zeitzonen-aware UTC-now (Python 3.12+)."""
    return datetime.now(timezone.utc)


@dataclass
class NotificationResult:
    notification_id: str
    rule_id: str
    success: bool
    recipients: list[str] = field(default_factory=list)
    subject: str = ""
    error_message: str | None = None
    sent_at: datetime = field(default_factory=_utcnow)


class NotificationEngine:
    """Versendet fällige Benachrichtigungen."""

    def __init__(
        self,
        engine: Engine,
        config: NotificationsConfig,
        mail_service: MailService,
        mail_config: MailConfig,
    ) -> None:
        self.engine = engine
        self.config = config
        self.mail_service = mail_service
        self.mail_config = mail_config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_due(self) -> list[NotificationResult]:
        """Sendet alle fälligen Benachrichtigungen."""
        due = self._get_due_notifications()
        results: list[NotificationResult] = []
        for rule in due:
            ctx = self._build_context(rule.id)
            result = self._send(rule, ctx)
            self._log(result)
            results.append(result)
        return results

    def send_test(self, notification_id: str) -> NotificationResult:
        """Versendet eine Test-Mail sofort, ignoriert den Scheduler."""
        rule = self.config.get(notification_id)
        if rule is None:
            return NotificationResult(
                notification_id=notification_id,
                rule_id=notification_id,
                success=False,
                error_message=f"Unbekannte Notification-ID: {notification_id}",
            )
        ctx = self._build_context(notification_id, test=True)
        result = self._send(rule, ctx, is_test=True)
        self._log(result)
        return result

    # ------------------------------------------------------------------
    # Scheduling
    # ------------------------------------------------------------------

    def _get_due_notifications(self) -> list:
        today = date.today()
        due: list = []
        for rule in self.config.rules:
            if not rule.enabled:
                continue
            if self._is_due(rule, today):
                due.append(rule)
        return due

    def _is_due(self, rule: Any, today: date) -> bool:
        schedule = (rule.schedule or "").lower()
        if schedule == "manual":
            return False
        if schedule == "daily":
            return today.weekday() < 7  # täglich
        if schedule == "monthly":
            return today.day == rule.day_of_month
        if schedule == "quarterly":
            return today.day == rule.day_of_month and today.month in (1, 4, 7, 10)
        # Cron-ähnliche Ausdrücke werden hier nicht voll unterstützt; nur daily/monthly/quarterly
        return False

    # ------------------------------------------------------------------
    # Rendering und Versand
    # ------------------------------------------------------------------

    def _build_context(self, rule_id: str, test: bool = False) -> dict[str, Any]:
        """Erzeugt den Template-Kontext für ``rule_id``."""
        ctx: dict[str, Any] = {
            "title": rule_id.replace("_", " ").title(),
            "summary": "Test-Nachricht" if test else "",
            "generated_at": _utcnow().isoformat(timespec="seconds"),
            "period": date.today().strftime("%Y-%m"),
        }
        # daily_wealth_report → NetWorth-Kontext
        if rule_id == "daily_wealth_report":
            nw = self._compute_net_worth()
            ctx["nw"] = nw
        elif rule_id == "monthly_portfolio":
            nw = self._compute_net_worth()
            ctx["nw"] = nw
            ctx["allocation"] = self._allocation(nw)
        elif rule_id == "rent_matrix":
            ctx["period"] = date.today().strftime("%Y-%m")
            ctx["results"] = self._rent_results(date.today())
        return ctx

    def _send(
        self, rule: Any, context: dict[str, Any], is_test: bool = False
    ) -> NotificationResult:
        html, text_body = render(rule.template, context)
        subject = f"{'[TEST] ' if is_test else ''}FinanzHub – {rule.id.replace('_', ' ').title()}"
        recipients = self.mail_config.test_recipient.split(",") if (
            self.mail_config.test_mode or is_test
        ) and self.mail_config.test_recipient else rule.recipients
        result: MailResult = self.mail_service.send(
            subject=subject,
            html_body=html,
            text_body=text_body,
            to_addresses=recipients,
        )
        return NotificationResult(
            notification_id=rule.id,
            rule_id=rule.id,
            success=result.success,
            recipients=result.recipients,
            subject=result.subject,
            error_message=result.error_message,
        )

    def _log(self, result: NotificationResult) -> None:
        try:
            with self.engine.begin() as conn:
                for recipient in result.recipients or ["unknown"]:
                    conn.execute(
                        text(
                            "INSERT INTO notification_log "
                            "(notification_id, recipient, subject, success, error_message) "
                            "VALUES (:nid, :r, :s, :ok, :err)"
                        ),
                        {
                            "nid": result.rule_id,
                            "r": recipient,
                            "s": result.subject,
                            "ok": result.success,
                            "err": result.error_message,
                        },
                    )
        except Exception as err:
            logger.error("Konnte notification_log nicht schreiben: %s", err)

    # ------------------------------------------------------------------
    # Daten-Helfer
    # ------------------------------------------------------------------

    def _compute_net_worth(self) -> dict[str, Any]:
        # Lazy imports, um Zyklen zu vermeiden
        from app.config_loader import load_assets, load_settings
        from app.core.portfolio_engine import calculate
        from app.data.price_service import PriceService

        try:
            load_settings()
            assets = load_assets()
        except SystemExit:
            return {"bank_total": 0, "securities_total": 0, "real_estate_equity": 0, "net_worth": 0, "positions": []}

        balances_rows = execute(
            self.engine,
            "SELECT account_id, balance, currency, recorded_at "
            "FROM balances b "
            "WHERE recorded_at = (SELECT MAX(recorded_at) FROM balances b2 "
            "                       WHERE b2.account_id = b.account_id) "
            "ORDER BY account_id",
        )
        from app.banking.base import BankBalance

        balances = [
            BankBalance(
                account_id=r["account_id"],
                account_name=r.get("account_name") or r["account_id"],
                iban=r.get("iban"),
                balance=float(r["balance"]),
                currency=r.get("currency", "EUR"),
            )
            for r in balances_rows
        ]
        price_service = PriceService(engine=self.engine)
        valuations = price_service.enrich_assets(assets)
        nw = calculate(assets, balances, valuations)
        return nw.to_dict()

    def _allocation(self, nw: dict[str, Any]) -> list[dict[str, Any]]:
        total = max(1.0, float(nw["net_worth"]))
        return [
            {"label": "Bank", "value": float(nw["bank_total"]), "share": float(nw["bank_total"]) / total * 100},
            {"label": "Depot", "value": float(nw["securities_total"]), "share": float(nw["securities_total"]) / total * 100},
            {"label": "Immobilien-EK", "value": float(nw["real_estate_equity"]), "share": float(nw["real_estate_equity"]) / total * 100},
        ]

    def _rent_results(self, period: date) -> list[dict[str, Any]]:
        from app.alerts.payment_monitor import check_rent
        from app.config_loader import load_assets, load_settings

        try:
            settings = load_settings()
            assets = load_assets()
        except SystemExit:
            return []
        results = check_rent(self.engine, assets, period, settings.matching)
        return [
            {
                "tenant": r.tenant,
                "expected_amount": r.expected_amount,
                "matched_amount": r.matched_amount,
                "status": r.status,
                "match_kind": r.match_kind,
            }
            for r in results
        ]


__all__ = ["NotificationEngine", "NotificationResult"]
