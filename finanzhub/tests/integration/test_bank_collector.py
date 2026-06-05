"""Integration-Tests für ``app.data.bank_collector``."""

from __future__ import annotations

from datetime import date

from app.banking.demo_client import DemoClient
from app.config_loader import BanksConfig
from app.data.bank_collector import BankCollector


def _banks_config() -> BanksConfig:
    return BanksConfig.model_validate(
        {
            "adapters": [
                {
                    "name": "demo",
                    "provider": "demo",
                    "enabled": True,
                    "options": {"seed": 42, "history_days": 30},
                }
            ],
            "active_adapter": "demo",
        }
    )


def _factory(provider: str, options: dict) -> DemoClient:
    return DemoClient(seed=options.get("seed", 42), history_days=options.get("history_days", 30))


class TestBankCollector:
    def test_first_pull_writes_transactions(self, db) -> None:
        collector = BankCollector(db, _banks_config(), factory=_factory)
        result = collector.collect_and_persist(since=date(2000, 1, 1))
        assert result.success
        assert result.transactions_imported > 0
        # Salden wurden geschrieben
        assert result.balances_imported == 3  # DemoClient hat 3 Konten

    def test_double_pull_is_idempotent(self, db) -> None:
        collector = BankCollector(db, _banks_config(), factory=_factory)
        r1 = collector.collect_and_persist(since=date(2000, 1, 1))
        r2 = collector.collect_and_persist(since=date(2000, 1, 1))
        assert r1.transactions_imported > 0
        assert r2.transactions_imported == 0  # nichts Neues

    def test_no_active_adapter_returns_fallback(self, db) -> None:
        cfg = BanksConfig.model_validate({"adapters": [], "active_adapter": None})
        collector = BankCollector(db, cfg, factory=_factory)
        result = collector.collect_and_persist()
        assert not result.success
        assert result.fallback_used is True

    def test_adapter_failure_returns_fallback(self, db, monkeypatch) -> None:
        cfg = BanksConfig.model_validate(
            {
                "adapters": [
                    {"name": "broken", "provider": "demo", "enabled": True, "options": {}}
                ],
                "active_adapter": "broken",
            }
        )

        def broken_factory(provider, options):
            client = DemoClient()
            client.test_connection = lambda: False  # type: ignore[assignment]
            return client

        collector = BankCollector(db, cfg, factory=broken_factory)
        result = collector.collect_and_persist()
        assert not result.success
        assert result.fallback_used
