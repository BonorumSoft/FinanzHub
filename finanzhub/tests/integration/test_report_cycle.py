"""End-to-End-Integration: Demo-Pull → Events → NetWorth."""

from __future__ import annotations

from datetime import date

from app.banking.demo_client import DemoClient
from app.config_loader import (
    AppSettings,
    BanksConfig,
    IncomeConfig,
    load_assets,
)
from app.core.portfolio_engine import calculate as calc_networth
from app.data.bank_collector import BankCollector
from app.data.event_detector import EventDetector


def _banks() -> BanksConfig:
    return BanksConfig.model_validate(
        {
            "adapters": [
                {
                    "name": "demo",
                    "provider": "demo",
                    "enabled": True,
                    "options": {"seed": 11, "history_days": 30},
                }
            ],
            "active_adapter": "demo",
        }
    )


def _factory(provider, options):
    return DemoClient(seed=options.get("seed", 42), history_days=options.get("history_days", 30))


class TestReportCycle:
    def test_full_cycle_with_demo_data(self, db) -> None:
        assets = load_assets("tests/fixtures")
        collector = BankCollector(db, _banks(), factory=_factory)
        res = collector.collect_and_persist(since=date(2000, 1, 1))
        assert res.success

        # Bank-Salden aus DB lesen
        from app.banking.base import BankBalance
        from app.data.db import execute

        rows = execute(
            db,
            "SELECT account_id, balance, currency, recorded_at "
            "FROM balances b "
            "WHERE recorded_at = (SELECT MAX(recorded_at) FROM balances b2 "
            "                       WHERE b2.account_id = b.account_id) "
            "ORDER BY account_id",
        )
        balances = [
            BankBalance(
                account_id=r["account_id"],
                account_name=r["account_id"],
                iban=None,
                balance=float(r["balance"]),
                currency=r.get("currency", "EUR"),
            )
            for r in rows
        ]
        # NetWorth ohne Marktdaten berechnen
        nw = calc_networth(assets, balances, [])
        assert nw.bank_total > 0
        assert nw.real_estate_equity > 0

        # Events
        detector = EventDetector(db, assets, IncomeConfig(), AppSettings())
        events = detector.detect_all()
        # Demo-Daten decken die letzten 30 Tage ab, also i. d. R. auch
        # Mieteingänge des aktuellen Monats. Es muss also irgendein
        # Event erkannt worden sein (Großbuchungen, Miet-Status o. ä.).
        assert len(events) > 0

    def test_double_pull_idempotent(self, db) -> None:
        collector = BankCollector(db, _banks(), factory=_factory)
        r1 = collector.collect_and_persist(since=date(2000, 1, 1))
        r2 = collector.collect_and_persist(since=date(2000, 1, 1))
        # Anzahl der Zeilen in transactions bleibt konstant
        from app.data.db import execute

        rows = execute(db, "SELECT COUNT(*) AS n FROM transactions")
        n = int(rows[0]["n"])
        assert n == r1.transactions_imported
        # Zweiter Lauf fügt nichts hinzu
        assert r2.transactions_imported == 0
