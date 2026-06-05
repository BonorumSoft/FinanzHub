"""Tests für ``app.data.dedup``."""

from __future__ import annotations

from app.data.dedup import generate_transaction_id, is_provider_id


class TestDedup:
    def test_same_transaction_produces_same_id(self) -> None:
        id1 = generate_transaction_id("2026-06-03", 1000.0, "MIETE A", "DE111")
        id2 = generate_transaction_id("2026-06-03", 1000.0, "MIETE A", "DE111")
        assert id1 == id2

    def test_different_amount_produces_different_id(self) -> None:
        id1 = generate_transaction_id("2026-06-03", 1000.0, "MIETE A")
        id2 = generate_transaction_id("2026-06-03", 1100.0, "MIETE A")
        assert id1 != id2

    def test_different_date_produces_different_id(self) -> None:
        id1 = generate_transaction_id("2026-06-03", 1000.0, "X")
        id2 = generate_transaction_id("2026-06-04", 1000.0, "X")
        assert id1 != id2

    def test_whitespace_normalized(self) -> None:
        id1 = generate_transaction_id("2026-06-03", 1000.0, "  MIETE  ", None)
        id2 = generate_transaction_id("2026-06-03", 1000.0, "Miete", None)
        assert id1 == id2

    def test_is_provider_id_heuristic(self) -> None:
        assert is_provider_id("ENABLE-BANK-12345ABCDEF")
        assert not is_provider_id("x")
        assert not is_provider_id("")


class TestCollector:
    def test_collector_skips_existing_transaction_ids(self, db, monkeypatch) -> None:
        """Zweiter Pull mit identischen Buchungen darf keine Duplikate anlegen."""
        from app.banking.demo_client import DemoClient
        from app.config_loader import BanksConfig
        from app.data.bank_collector import BankCollector

        cfg = BanksConfig.model_validate(
            {
                "adapters": [
                    {
                        "name": "demo",
                        "provider": "demo",
                        "enabled": True,
                        "options": {"seed": 7, "history_days": 30},
                    }
                ],
                "active_adapter": "demo",
            }
        )
        # Factory liefert immer eine frische Instanz
        def factory(provider, options):
            return DemoClient(seed=options.get("seed", 42), history_days=options.get("history_days", 30))

        collector = BankCollector(db, cfg, factory=factory)
        r1 = collector.collect_and_persist(since=__import__("datetime").date(2000, 1, 1))
        r2 = collector.collect_and_persist(since=__import__("datetime").date(2000, 1, 1))
        # Beide Läufe sollen grundsätzlich erfolgreich sein
        assert r1.success
        assert r2.success
        # r2 darf keine neuen Transaktionen einfügen
        assert r2.transactions_imported == 0
