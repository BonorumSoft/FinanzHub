"""Tests für app.inbox.transaction_matcher."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text

from app.config_loader import InboxMatchingConfig
from app.data.db import build_engine
from app.inbox.receipt_extractor import ExtractedReceipt
from app.inbox.transaction_matcher import TransactionMatcher

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def engine():
    """In-Memory-SQLite mit minimalem transactions-Schema."""
    eng = build_engine("sqlite:///:memory:")
    with eng.begin() as conn:
        conn.execute(text(
            "CREATE TABLE transactions ("
            "  transaction_id TEXT PRIMARY KEY,"
            "  booking_date DATE,"
            "  amount NUMERIC,"
            "  description TEXT,"
            "  counterparty_name TEXT,"
            "  counterparty_iban TEXT,"
            "  is_internal BOOLEAN DEFAULT 0"
            ")"
        ))
    yield eng
    eng.dispose()


@pytest.fixture()
def matcher(engine) -> TransactionMatcher:
    return TransactionMatcher(engine, InboxMatchingConfig())


def _insert(engine, **kwargs: Any) -> None:
    # SQLite bind-Adapter akzeptiert kein Decimal — zu float konvertieren
    if "amount" in kwargs and isinstance(kwargs["amount"], Decimal):
        kwargs["amount"] = float(kwargs["amount"])
    cols = ", ".join(kwargs.keys())
    placeholders = ", ".join(f":{k}" for k in kwargs)
    with engine.begin() as conn:
        conn.execute(text(f"INSERT INTO transactions ({cols}) VALUES ({placeholders})"), kwargs)


def _receipt(amount: float = 47.90, d: str = "2026-06-04", merchant: str | None = None) -> ExtractedReceipt:
    return ExtractedReceipt(date=d, amount=amount, merchant=merchant, confidence=0.9)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_exact_match_returns_high_confidence(matcher, engine):
    _insert(engine, transaction_id="TX-1", booking_date=date(2026, 6, 4),
            amount=Decimal("-47.90"), description="REWE", counterparty_name="REWE STUHR")
    result = matcher.find_match(_receipt(amount=47.90, d="2026-06-04", merchant="REWE"))
    assert result.transaction_id == "TX-1"
    assert result.confidence >= 0.85
    assert "exact" in result.method


def test_amount_tolerance_respected(matcher, engine):
    """47.90€ Beleg matched 48.10€ TX wenn Toleranz 0.50€."""
    _insert(engine, transaction_id="TX-2", booking_date=date(2026, 6, 5),
            amount=Decimal("-48.10"), description="X", counterparty_name="X")
    result = matcher.find_match(_receipt(amount=47.90, d="2026-06-05"))
    assert result.transaction_id == "TX-2"
    assert result.confidence >= 0.70


def test_merchant_substring_increases_confidence(matcher, engine):
    """REWE im Händler + 'REWE STUHR 1234' in TX-Description → +0.10 confidence."""
    _insert(engine, transaction_id="TX-A", booking_date=date(2026, 6, 4),
            amount=Decimal("-47.90"), description="X", counterparty_name="ANDERER")
    _insert(engine, transaction_id="TX-B", booking_date=date(2026, 6, 4),
            amount=Decimal("-47.90"), description="REWE STUHR 1234", counterparty_name="REWE")
    result = matcher.find_match(_receipt(amount=47.90, d="2026-06-04", merchant="REWE"))
    assert result.transaction_id == "TX-B"
    # Mit Merchant-Match: 0.95; ohne: 0.85
    assert result.confidence >= 0.90


def test_no_match_when_amount_missing(matcher, engine):
    """Kein amount → sofort no_match."""
    receipt = ExtractedReceipt(date="2026-06-04", amount=None, confidence=0.9)
    result = matcher.find_match(receipt)
    assert result.transaction_id is None
    assert result.confidence == 0.0


def test_no_match_when_date_outside_window(matcher, engine):
    """TX 30 Tage entfernt → kein Match."""
    _insert(engine, transaction_id="TX-OLD", booking_date=date(2026, 5, 1),
            amount=Decimal("-47.90"), description="X", counterparty_name="X")
    result = matcher.find_match(_receipt(amount=47.90, d="2026-06-04"))
    assert result.transaction_id is None


def test_multiple_candidates_best_wins(matcher, engine):
    """Mehrere Kandidaten: höchste Konfidenz gewinnt."""
    _insert(engine, transaction_id="TX-NEAR", booking_date=date(2026, 6, 4),
            amount=Decimal("-47.90"), description="X", counterparty_name="UNBEKANNT")
    _insert(engine, transaction_id="TX-FAR", booking_date=date(2026, 6, 7),
            amount=Decimal("-47.90"), description="REWE STUHR 42", counterparty_name="REWE")
    result = matcher.find_match(_receipt(amount=47.90, d="2026-06-04", merchant="REWE"))
    # Beide haben exakten Betrag, aber TX-FAR hat Merchant-Match (0.95) und
    # liegt 3 Tage entfernt (im Fenster); TX-NEAR hat kein Merchant (0.85)
    assert result.transaction_id == "TX-FAR"
    assert result.confidence >= 0.90


def test_only_outgoing_transactions_considered(matcher, engine):
    """Eingehende Buchungen (+) werden ignoriert (Vorzeichenfilter in SQL)."""
    _insert(engine, transaction_id="TX-IN", booking_date=date(2026, 6, 4),
            amount=Decimal("+47.90"), description="GEHALT", counterparty_name="AG")
    result = matcher.find_match(_receipt(amount=47.90, d="2026-06-04"))
    assert result.transaction_id is None


def test_invalid_date_in_receipt(matcher, engine):
    """Ungültiges ISO-Datum → no_match, kein Crash."""
    receipt = ExtractedReceipt(date="not-a-date", amount=47.90, confidence=0.9)
    result = matcher.find_match(receipt)
    assert result.transaction_id is None


def test_match_method_label(matcher, engine):
    """method-Label ist eines der dokumentierten Werte."""
    _insert(engine, transaction_id="TX-Z", booking_date=date(2026, 6, 4),
            amount=Decimal("-47.90"), description="X", counterparty_name="X")
    result = matcher.find_match(_receipt(amount=47.90, d="2026-06-04"))
    assert result.method in {"exact_amount_date", "exact_amount_merchant", "fuzzy", "amount_only", "no_match"}


def test_merchant_normalized(matcher, engine):
    """Sonderzeichen im Händler werden ignoriert (REWE. GmbH == REWE GMBH)."""
    _insert(engine, transaction_id="TX-N1", booking_date=date(2026, 6, 4),
            amount=Decimal("-47.90"), description="X", counterparty_name="REWE GMBH")
    result = matcher.find_match(_receipt(amount=47.90, d="2026-06-04", merchant="REWE. GmbH"))
    assert result.transaction_id == "TX-N1"
    assert result.confidence >= 0.90
