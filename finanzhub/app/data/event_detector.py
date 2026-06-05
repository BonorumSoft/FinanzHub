"""Zentrale Event-Engine.

Erkennt alle in der Spec definierten Event-Typen. Jeder Detector ist eine
eigene ``_detect_<event_type>``-Methode; die Ergebnisse werden
anschließend dedupliziert und in die ``events``-Tabelle geschrieben.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy.engine import Engine

from app.alerts.payment_monitor import check_rent
from app.alerts.substance_monitor import SubstanceEvent
from app.alerts.substance_monitor import detect_all as detect_substance
from app.config_loader import (
    AppSettings,
    AssetsConfig,
    IncomeConfig,
    MatchingConfig,
    VermoegenConfig,
)
from app.core.cashflow_engine import find_negative_cashflow_months, monthly_cashflow
from app.data.db import insert_or_ignore
from app.logger import get_logger

logger = get_logger(__name__)


# Event-Typen (14 insgesamt, dokumentiert in docs/events.md)
EVENT_TYPES: tuple[str, ...] = (
    "rent_overdue",
    "rent_partial",
    "rent_overpaid",
    "rent_multiple",
    "substance_draw",
    "substance_consecutive_decline",
    "low_liquidity",
    "large_outgoing",
    "internal_transfer_large",
    "negative_object_cashflow",
    "portfolio_loss",
    "low_reserve_ratio",
    "rent_indexation_due",
    "nk_abrechnung_due",
)


@dataclass
class Event:
    event_type: str
    entity_id: str
    period: str
    severity: str = "info"  # "info" | "warning" | "critical"
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "entity_id": self.entity_id,
            "period": self.period,
            "severity": self.severity,
            "details": self.details,
        }


class EventDetector:
    """Liest Daten aus der DB und Konfiguration und erzeugt :class:`Event`-Records."""

    def __init__(
        self,
        engine: Engine,
        assets: AssetsConfig,
        income: IncomeConfig,
        settings: AppSettings,
    ) -> None:
        self.engine = engine
        self.assets = assets
        self.income = income
        self.settings = settings
        self.matching: MatchingConfig = settings.matching
        self.wealth: VermoegenConfig = settings.vermoegen

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect_all(self) -> list[Event]:
        events: list[Event] = []
        events.extend(self._detect_rent_overdue())
        events.extend(self._detect_rent_partial())
        events.extend(self._detect_rent_overpaid())
        events.extend(self._detect_rent_multiple())
        events.extend(self._detect_substance_events())
        events.extend(self._detect_low_liquidity())
        events.extend(self._detect_large_outgoing())
        events.extend(self._detect_internal_transfer_large())
        events.extend(self._detect_negative_object_cashflow())
        events.extend(self._detect_portfolio_loss())
        events.extend(self._detect_low_reserve_ratio())
        events.extend(self._detect_rent_indexation_due())
        events.extend(self._detect_nk_abrechnung_due())
        return self._deduplicate_and_persist(events)

    # ------------------------------------------------------------------
    # Rent-Events
    # ------------------------------------------------------------------

    def _detect_rent_overdue(self) -> list[Event]:
        today = date.today()
        results = check_rent(self.engine, self.assets, today, self.matching)
        out: list[Event] = []
        for r in results:
            if r.status in ("offen", "teilweise"):
                grace = self.matching.warnung_ab_tag
                severity = "critical" if r.status == "offen" else "warning"
                out.append(
                    Event(
                        event_type="rent_overdue",
                        entity_id=r.tenant,
                        period=today.strftime("%Y-%m"),
                        severity=severity,
                        details={
                            "expected": r.expected_amount,
                            "matched": r.matched_amount,
                            "grace_days": grace,
                            "status": r.status,
                        },
                    )
                )
        return out

    def _detect_rent_partial(self) -> list[Event]:
        today = date.today()
        results = check_rent(self.engine, self.assets, today, self.matching)
        return [
            Event(
                event_type="rent_partial",
                entity_id=r.tenant,
                period=today.strftime("%Y-%m"),
                severity="warning",
                details={
                    "expected": r.expected_amount,
                    "matched": r.matched_amount,
                    "missing": round(r.expected_amount - r.matched_amount, 2),
                },
            )
            for r in results
            if r.status == "teilweise"
        ]

    def _detect_rent_overpaid(self) -> list[Event]:
        today = date.today()
        results = check_rent(self.engine, self.assets, today, self.matching)
        return [
            Event(
                event_type="rent_overpaid",
                entity_id=r.tenant,
                period=today.strftime("%Y-%m"),
                severity="info",
                details={
                    "expected": r.expected_amount,
                    "matched": r.matched_amount,
                    "overpaid": round(r.matched_amount - r.expected_amount, 2),
                },
            )
            for r in results
            if r.status == "zu_viel"
        ]

    def _detect_rent_multiple(self) -> list[Event]:
        today = date.today()
        results = check_rent(self.engine, self.assets, today, self.matching)
        return [
            Event(
                event_type="rent_multiple",
                entity_id=r.tenant,
                period=today.strftime("%Y-%m"),
                severity="warning",
                details={
                    "transactions": len(r.matched_transactions),
                    "matched": r.matched_amount,
                },
            )
            for r in results
            if r.status == "mehrfach"
        ]

    # ------------------------------------------------------------------
    # Substanz
    # ------------------------------------------------------------------

    def _detect_substance_events(self) -> list[Event]:
        substance_events: list[SubstanceEvent] = detect_substance(self.engine, self.settings)
        out: list[Event] = []
        for s in substance_events:
            event_type = (
                "substance_consecutive_decline"
                if s.trigger == "consecutive_decline"
                else "substance_draw"
            )
            out.append(
                Event(
                    event_type=event_type,
                    entity_id="portfolio",
                    period=date.today().strftime("%Y-%m"),
                    severity="critical",
                    details=s.to_dict(),
                )
            )
        return out

    # ------------------------------------------------------------------
    # Liquidität
    # ------------------------------------------------------------------

    def _detect_low_liquidity(self) -> list[Event]:
        from app.data.db import execute

        threshold = self.wealth.schwellwert_liquiditaet_euro
        rows = execute(
            self.engine,
            "SELECT account_id, balance FROM balances b "
            "WHERE recorded_at = (SELECT MAX(recorded_at) FROM balances b2 "
            "                       WHERE b2.account_id = b.account_id)",
        )
        out: list[Event] = []
        for r in rows:
            if float(r["balance"]) < threshold:
                out.append(
                    Event(
                        event_type="low_liquidity",
                        entity_id=str(r["account_id"]),
                        period=date.today().strftime("%Y-%m"),
                        severity="warning",
                        details={
                            "balance": float(r["balance"]),
                            "threshold": threshold,
                        },
                    )
                )
        return out

    # ------------------------------------------------------------------
    # Buchungen
    # ------------------------------------------------------------------

    def _detect_large_outgoing(self) -> list[Event]:
        from app.data.db import execute

        threshold = self.wealth.schwellwert_grosse_buchung_euro
        rows = execute(
            self.engine,
            "SELECT transaction_id, account_id, amount, description, booking_date "
            "FROM transactions WHERE amount < -:t AND is_internal = FALSE "
            "AND booking_date >= :since",
            {
                "t": threshold,
                "since": date.today().replace(day=1).isoformat(),
            },
        )
        return [
            Event(
                event_type="large_outgoing",
                entity_id=str(r["transaction_id"]),
                period=str(r["booking_date"]),
                severity="info",
                details={
                    "amount": float(r["amount"]),
                    "account_id": r["account_id"],
                    "description": r["description"],
                },
            )
            for r in rows
        ]

    def _detect_internal_transfer_large(self) -> list[Event]:
        from app.data.db import execute

        threshold = self.wealth.schwellwert_grosse_buchung_euro
        rows = execute(
            self.engine,
            "SELECT transaction_id, account_id, amount, description, booking_date "
            "FROM transactions WHERE amount < -:t AND is_internal = TRUE "
            "AND booking_date >= :since",
            {
                "t": threshold,
                "since": date.today().replace(day=1).isoformat(),
            },
        )
        return [
            Event(
                event_type="internal_transfer_large",
                entity_id=str(r["transaction_id"]),
                period=str(r["booking_date"]),
                severity="info",
                details={
                    "amount": float(r["amount"]),
                    "account_id": r["account_id"],
                    "description": r["description"],
                },
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Immobilien-Cashflow
    # ------------------------------------------------------------------

    def _detect_negative_object_cashflow(self) -> list[Event]:
        out: list[Event] = []
        today = date.today()
        for asset in self.assets.real_estate:
            cashflows = monthly_cashflow(asset, months=12)
            negatives = find_negative_cashflow_months(cashflows)
            for c in negatives:
                out.append(
                    Event(
                        event_type="negative_object_cashflow",
                        entity_id=asset.name,
                        period=f"{c.year:04d}-{c.month:02d}",
                        severity="warning",
                        details={
                            "net_cashflow": c.net_cashflow,
                            "rent": c.rent,
                            "loan_payment": c.loan_payment,
                        },
                    )
                )
        return out

    # ------------------------------------------------------------------
    # Portfolio
    # ------------------------------------------------------------------

    def _detect_portfolio_loss(self) -> list[Event]:
        threshold = self.wealth.schwellwert_portfolio_verlust_prozent
        out: list[Event] = []
        for sec in self.assets.securities:
            if sec.purchase_price <= 0 or sec.current_value is None:
                continue
            pnl_pct = (sec.current_value - sec.purchase_price) / sec.purchase_price * 100.0
            if pnl_pct <= -abs(threshold):
                out.append(
                    Event(
                        event_type="portfolio_loss",
                        entity_id=sec.isin,
                        period=date.today().strftime("%Y-%m"),
                        severity="critical",
                        details={
                            "purchase_price": sec.purchase_price,
                            "current_value": sec.current_value,
                            "pnl_percent": round(pnl_pct, 2),
                            "threshold": threshold,
                        },
                    )
                )
        return out

    def _detect_low_reserve_ratio(self) -> list[Event]:
        from app.core.rentability_engine import calculate as calc

        threshold = self.wealth.schwellwert_ruecklage_prozent
        out: list[Event] = []
        for asset in self.assets.real_estate:
            report = calc(asset)
            if report.cold_rent_annual <= 0:
                continue
            reserve_ratio = (
                asset.maintenance_reserve_monthly * 12.0 / report.cold_rent_annual * 100.0
            )
            if reserve_ratio < threshold:
                out.append(
                    Event(
                        event_type="low_reserve_ratio",
                        entity_id=asset.name,
                        period=date.today().strftime("%Y-%m"),
                        severity="warning",
                        details={
                            "reserve_ratio": round(reserve_ratio, 2),
                            "threshold": threshold,
                        },
                    )
                )
        return out

    # ------------------------------------------------------------------
    # Zeitgesteuerte Erinnerungen
    # ------------------------------------------------------------------

    def _detect_rent_indexation_due(self) -> list[Event]:
        out: list[Event] = []
        for asset in self.assets.real_estate:
            if not asset.tenants:
                continue
            last_indexed_year = date.today().year - 1
            # Spec: alle 12 Monate Indexierung prüfen; Vereinfachung: jeden
            # Januar für jedes Objekt
            if date.today().month == 1 and asset.tenants:
                out.append(
                    Event(
                        event_type="rent_indexation_due",
                        entity_id=asset.name,
                        period=date.today().strftime("%Y-%m"),
                        severity="info",
                        details={"last_indexed_year": last_indexed_year},
                    )
                )
        return out

    def _detect_nk_abrechnung_due(self) -> list[Event]:
        # NK-Abrechnung jährlich, typischerweise im Q1 fürs Vorjahr
        if date.today().month != 1:
            return []
        return [
            Event(
                event_type="nk_abrechnung_due",
                entity_id=asset.name,
                period=date.today().strftime("%Y-%m"),
                severity="info",
                details={"year": date.today().year - 1},
            )
            for asset in self.assets.real_estate
        ]

    # ------------------------------------------------------------------
    # Persistenz
    # ------------------------------------------------------------------

    def _deduplicate_and_persist(self, events: list[Event]) -> list[Event]:
        persisted: list[Event] = []
        for ev in events:
            row = {
                "event_type": ev.event_type,
                "entity_id": ev.entity_id,
                "period": ev.period,
                "details": json.dumps(ev.details, default=str),
            }
            try:
                if insert_or_ignore(
                    self.engine,
                    "events",
                    ("event_type", "entity_id", "period"),
                    row,
                ):
                    persisted.append(ev)
            except Exception as err:
                logger.error("Konnte Event %s nicht persistieren: %s", ev.event_type, err)
        logger.info("EventDetector: %d neue Events persistiert", len(persisted))
        return persisted


__all__ = ["EVENT_TYPES", "Event", "EventDetector"]
