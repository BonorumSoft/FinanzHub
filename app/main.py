"""Haupteinstiegspunkt – Startup-Sequenz, SIGTERM-Handling, Scheduler-Start.

Die Sequenz folgt strikt der Spec:

1. Logger initialisieren
2. Konfiguration laden + validieren (Exit 1 bei Fehler)
3. DB verbinden (Retry-Loop, RuntimeError wenn nicht erreichbar)
4. Migrationen anwenden
5. SMTP prüfen (nicht-fatal, WARNING bei Fehler)
6. Erster Report-Zyklus ausführen
7. Scheduler starten
8. Auf SIGTERM/SIGINT warten → graceful shutdown
"""

from __future__ import annotations

import os
import signal
import sys
from datetime import date
from typing import Any

from sqlalchemy.engine import Engine

from app.config_loader import (
    load_all,
)
from app.data.bank_collector import BankCollector
from app.data.db import apply_migrations, build_engine, wait_for_db
from app.data.event_detector import EventDetector
from app.data.price_service import PriceService
from app.logger import configure_logging, get_logger
from app.notifications.engine import NotificationEngine
from app.output.mail_service import MailService
from app.scheduler import build_scheduler

logger = get_logger(__name__)


def _startup_configure_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO")
    log_file = os.environ.get("LOG_FILE") or None
    configure_logging(level=level, log_file=log_file)


def _load_config_or_exit() -> dict[str, Any]:
    try:
        return load_all()
    except SystemExit:
        raise


def _connect_db() -> Engine:
    engine = build_engine()
    wait_for_db(engine, attempts=15, delay=3.0)
    return engine


def _check_smtp(mail_cfg: Any) -> None:
    try:
        import smtplib

        with smtplib.SMTP(mail_cfg.host, mail_cfg.port, timeout=5) as smtp:
            smtp.ehlo()
            logger.info("SMTP erreichbar: %s:%d", mail_cfg.host, mail_cfg.port)
    except Exception as err:
        logger.warning("SMTP nicht erreichbar: %s – Benachrichtigungen werden übersprungen", err)


def _first_report_cycle(engine: Engine, configs: dict[str, Any]) -> None:
    """Einmaliger Lauf beim Start: Pull → Prices → NetWorth → Events → Notify."""
    try:
        settings = configs["settings"]
        assets = configs["assets"]
        banks = configs["banks"]
        mail_cfg = configs["mail"]
        notif_cfg = configs["notifications"]
        income = configs["income"]

        collector = BankCollector(engine, banks)
        res = collector.collect_and_persist()
        logger.info("Startup-Pull: %d Buchungen, Fallback=%s", res.transactions_imported, res.fallback_used)

        try:
            price_service = PriceService(engine=engine)
            price_service.enrich_assets(assets)
        except Exception as err:
            logger.warning("Marktdaten-Update fehlgeschlagen: %s", err)

        detector = EventDetector(engine, assets, income, settings)
        events = detector.detect_all()
        logger.info("Startup-Events: %d neu", len(events))

        mail = MailService(mail_cfg)
        ne = NotificationEngine(engine, notif_cfg, mail, mail_cfg)
        results = ne.run_due()
        logger.info("Startup-Notifications: %d versendet", len(results))
    except Exception as err:
        logger.error("Erster Report-Zyklus fehlgeschlagen: %s", err, exc_info=True)


def _build_cycle_functions(engine: Engine, configs: dict[str, Any]) -> dict[str, Any]:
    settings = configs["settings"]
    assets = configs["assets"]
    banks = configs["banks"]
    mail_cfg = configs["mail"]
    notif_cfg = configs["notifications"]
    income = configs["income"]

    def daily() -> None:
        try:
            res = BankCollector(engine, banks).collect_and_persist()
            logger.info("[daily] Pull: %d Buchungen", res.transactions_imported)
            try:
                PriceService(engine=engine).enrich_assets(assets)
            except Exception as err:
                logger.warning("[daily] Marktdaten: %s", err)
            detector = EventDetector(engine, assets, income, settings)
            events = detector.detect_all()
            logger.info("[daily] %d neue Events", len(events))
            ne = NotificationEngine(engine, notif_cfg, MailService(mail_cfg), mail_cfg)
            ne.run_due()
        except Exception as err:
            logger.error("[daily] Zyklus fehlgeschlagen: %s", err, exc_info=True)

    def monthly() -> None:
        try:
            detector = EventDetector(engine, assets, income, settings)
            events = detector.detect_all()
            ne = NotificationEngine(engine, notif_cfg, MailService(mail_cfg), mail_cfg)
            for r in ne.run_due():
                logger.info("[monthly] %s -> %s", r.notification_id, r.success)
        except Exception as err:
            logger.error("[monthly] Zyklus fehlgeschlagen: %s", err, exc_info=True)

    def quarterly() -> None:
        logger.info("[quarterly] Quartalszyklus gestartet (%s)", date.today().isoformat())
        monthly()

    return {"daily": daily, "monthly": monthly, "quarterly": quarterly}


def main() -> int:
    _startup_configure_logging()
    logger.info("FinanzHub startet")

    try:
        configs = _load_config_or_exit()
    except SystemExit:
        return 1

    try:
        engine = _connect_db()
    except RuntimeError as err:
        logger.error("DB-Connect fehlgeschlagen: %s", err)
        return 1

    try:
        new_migrations = apply_migrations(engine)
        if new_migrations:
            logger.info("Migrationen angewendet: %s", new_migrations)
    except Exception as err:
        logger.error("Migrationen fehlgeschlagen: %s", err, exc_info=True)
        return 1

    mail_cfg = configs["mail"]
    _check_smtp(mail_cfg)

    _first_report_cycle(engine, configs)

    cycles = _build_cycle_functions(engine, configs)
    inbox_cfg = configs.get("inbox")
    inbox_poll_callable = None
    inbox_poll_seconds = 60
    if inbox_cfg is not None and getattr(inbox_cfg, "enabled", False):
        from app.inbox.inbox_engine import InboxEngine

        def _inbox_poll() -> None:
            try:
                InboxEngine(inbox_cfg, engine).process_inbox()
            except Exception as err:  # noqa: BLE001
                logger.error("[inbox] Polling fehlgeschlagen: %s", err, exc_info=True)

        inbox_poll_callable = _inbox_poll
        inbox_poll_seconds = inbox_cfg.imap.poll_interval_seconds
        logger.info("Beleg-Inbox aktiviert (Intervall: %ds)", inbox_poll_seconds)
    else:
        logger.info("Beleg-Inbox deaktiviert")

    scheduler = build_scheduler(
        daily=cycles["daily"],
        monthly=cycles["monthly"],
        quarterly=cycles["quarterly"],
        inbox_poll=inbox_poll_callable,
        inbox_poll_seconds=inbox_poll_seconds,
    )

    stop_requested = {"flag": False}

    def _handle_signal(signum: int, frame: Any) -> None:  # noqa: ARG001
        logger.info("Signal %s empfangen, fahre herunter", signum)
        stop_requested["flag"] = True
        try:
            scheduler.shutdown(wait=False)
        except Exception as err:
            logger.warning("Scheduler shutdown fehlerhaft: %s", err)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    try:
        logger.info("Scheduler startet – warte auf Cron-Trigger")
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        _handle_signal(signal.SIGINT, None)

    logger.info("FinanzHub beendet sich")
    return 0


if __name__ == "__main__":
    sys.exit(main())
