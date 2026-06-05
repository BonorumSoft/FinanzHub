"""Tests für ``app.data.event_detector``."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from app.config_loader import AppSettings, IncomeConfig, load_assets
from app.data.event_detector import EventDetector


def _insert_tx(engine, **kwargs: object) -> None:
    defaults: dict = {
        "transaction_id": kwargs.get("transaction_id", "tx-default"),
        "account_id": "DE_GIRO",
        "booking_date": kwargs.get("booking_date", "2026-06-03"),
        "amount": kwargs.get("amount", 0.0),
        "currency": "EUR",
        "description": kwargs.get("description", "X"),
        "is_internal": kwargs.get("is_internal", False),
    }
    placeholders = ", ".join(f":{k}" for k in defaults.keys())
    cols = ", ".join(defaults.keys())
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO transactions ({cols}) VALUES ({placeholders})"),
            defaults,
        )


@pytest.fixture
def assets():
    return load_assets("tests/fixtures")


@pytest.fixture
def detector(db, assets):
    return EventDetector(
        engine=db,
        assets=assets,
        income=IncomeConfig(),
        settings=AppSettings(),
    )


class TestRentEvents:
    def test_rent_overdue_detected(self, detector, db) -> None:
        # Keine Mieteingänge → alle offen
        events = detector._detect_rent_overdue()
        assert any(e.event_type == "rent_overdue" for e in events)

    def test_rent_overdue_not_duplicated_on_second_run(self, detector) -> None:
        first = detector._detect_rent_overdue()
        assert first
        # Persistieren simuliert den ersten Lauf
        detector._deduplicate_and_persist(first)
        # Zweiter Lauf darf nichts Neues erzeugen, wenn die DB existiert UND die UNIQUE greift
        second = detector._detect_rent_overdue()
        persisted_second = detector._deduplicate_and_persist(second)
        assert persisted_second == []


class TestBuchungsEvents:
    def test_large_outgoing_detected(self, detector, db) -> None:
        _insert_tx(db, transaction_id="big1", amount=-750.0, description="GROSS")
        events = detector._detect_large_outgoing()
        assert any(e.event_type == "large_outgoing" for e in events)

    def test_internal_transfer_not_triggers_large_outgoing(self, detector, db) -> None:
        _insert_tx(db, transaction_id="big2", amount=-1000.0, description="INTERNAL", is_internal=True)
        events = detector._detect_large_outgoing()
        # Sollte nicht ausgelöst werden, weil is_internal=True
        assert all(e.event_type != "large_outgoing" for e in events)


class TestSubstanzEvents:
    def test_substance_events_empty_when_no_history(self, detector) -> None:
        assert detector._detect_substance_events() == []


class TestPersistenz:
    def test_deduplicate_and_persist_idempotent(self, detector) -> None:
        from app.data.event_detector import Event

        ev = Event(
            event_type="test_event",
            entity_id="X",
            period="2026-06",
            severity="info",
            details={"foo": "bar"},
        )
        first = detector._deduplicate_and_persist([ev])
        second = detector._deduplicate_and_persist([ev])
        assert len(first) == 1
        assert second == []  # kein zweites Mal persistiert
