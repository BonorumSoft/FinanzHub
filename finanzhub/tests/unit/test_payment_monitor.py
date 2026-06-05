"""Tests für ``app.alerts.payment_monitor`` (Integrations-Level)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import text

from app.alerts.payment_monitor import check_income, check_rent
from app.config_loader import (
    IncomeConfig,
    MatchingConfig,
    load_assets,
)


@pytest.fixture
def assets():
    return load_assets("tests/fixtures")


def _insert_tx(engine, **kwargs: object) -> None:
    defaults = {
        "transaction_id": kwargs.get("transaction_id", "tx-" + str(kwargs.get("amount", 0))),
        "account_id": "DE_GIRO",
        "booking_date": kwargs.get("booking_date", "2026-06-03"),
        "amount": kwargs.get("amount", 1000.0),
        "currency": "EUR",
        "description": kwargs.get("description", "MIETE"),
        "counterparty_iban": kwargs.get("counterparty_iban"),
        "counterparty_name": kwargs.get("counterparty_name"),
        "is_internal": False,
    }
    placeholders = ", ".join(f":{k}" for k in defaults.keys())
    cols = ", ".join(defaults.keys())
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO transactions ({cols}) VALUES ({placeholders})"),
            defaults,
        )


class TestPaymentMonitor:
    def test_iban_match_takes_priority_over_keyword(self, db, assets) -> None:
        _insert_tx(
            db,
            transaction_id="t1",
            amount=1000.0,
            description="MIETE A",
            counterparty_iban="DE11111111111111111111",
            booking_date="2026-06-03",
        )
        results = check_rent(db, assets, date(2026, 6, 1), MatchingConfig())
        # Mieter A matched per IBAN, Mieter B bleibt offen
        a = next(r for r in results if r.tenant == "Mieter A")
        assert a.match_kind == "iban"
        assert a.status == "bezahlt"

    def test_partial_payment_detected(self, db, assets) -> None:
        _insert_tx(
            db,
            amount=800.0,
            counterparty_iban="DE11111111111111111111",
            booking_date="2026-06-03",
        )
        results = check_rent(db, assets, date(2026, 6, 1), MatchingConfig())
        a = next(r for r in results if r.tenant == "Mieter A")
        assert a.status == "teilweise"

    def test_claimed_transaction_not_available(self, db, assets) -> None:
        # Eine Buchung über A's IBAN matched A zuerst. Da nur eine einzige
        # Buchung da ist und A's erwartete Miete 1000€ beträgt, ist A bezahlt.
        # B geht leer aus, weil die Buchung bereits "claimed" wurde.
        _insert_tx(
            db,
            transaction_id="claimed-1",
            amount=1000.0,
            counterparty_iban="DE11111111111111111111",
            booking_date="2026-06-03",
        )
        results = check_rent(db, assets, date(2026, 6, 1), MatchingConfig())
        a = next(r for r in results if r.tenant == "Mieter A")
        b = next(r for r in results if r.tenant == "Mieter B")
        assert a.status == "bezahlt"
        assert b.status == "offen"

    def test_tolerance_window(self, db, assets) -> None:
        # Tag +5 ist im Fenster
        _insert_tx(
            db,
            amount=1000.0,
            counterparty_iban="DE11111111111111111111",
            booking_date="2026-06-08",
        )
        results = check_rent(db, assets, date(2026, 6, 1), MatchingConfig(standard_toleranz_tage=5))
        a = next(r for r in results if r.tenant == "Mieter A")
        assert a.status == "bezahlt"

    def test_check_income(self, db) -> None:
        _insert_tx(
            db,
            amount=3500.0,
            description="ARBEITGEBER GEHALT",
            booking_date="2026-06-25",
        )
        income = IncomeConfig.model_validate(
            {
                "expected_income": [
                    {
                        "name": "Gehalt",
                        "amount_min": 3000.0,
                        "expected_by_day": 25,
                        "keywords": ["GEHALT"],
                    }
                ]
            }
        )
        results = check_income(db, income, date(2026, 6, 1))
        assert results[0].status == "bezahlt"
        assert results[0].matched_amount == 3500.0
