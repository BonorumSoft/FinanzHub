"""Tests für ``app.banking.csv_adapter`` und ``app.banking.fints_adapter``."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from app.banking.csv_adapter import CSVAdapter
from app.banking.fints_adapter import FinTSAdapter


class TestCSVAdapter:
    def _write_csv(self, tmp_path: Path) -> Path:
        p = tmp_path / "tx.csv"
        p.write_text(
            "Datum;Betrag;Verwendungszweck;Empfänger;IBAN\n"
            "03.06.2026;-100,00;REWE;REWE;DE99\n"
            "04.06.2026;1500,50;MIETE A;Mieter A;DE11\n"
            "05.06.2026;-50,25;STROM;STADTWERKE;DE22\n",
            encoding="utf-8",
        )
        return p

    def test_connection(self, tmp_path: Path) -> None:
        a = CSVAdapter(str(self._write_csv(tmp_path)))
        assert a.test_connection() is True

    def test_connection_missing_file(self, tmp_path: Path) -> None:
        a = CSVAdapter(str(tmp_path / "missing.csv"))
        assert a.test_connection() is False

    def test_get_transactions(self, tmp_path: Path) -> None:
        a = CSVAdapter(str(self._write_csv(tmp_path)))
        txs = a.get_transactions(date(2000, 1, 1))
        assert len(txs) == 3
        # Beträge sind deutsches Format: "1500,50" → 1500.50
        miete = next(t for t in txs if t.amount > 0)
        assert miete.amount == 1500.50
        assert miete.counterparty_iban == "DE11"
        assert miete.description == "MIETE A"

    def test_since_filter(self, tmp_path: Path) -> None:
        a = CSVAdapter(str(self._write_csv(tmp_path)))
        txs = a.get_transactions(date(2027, 1, 1))
        assert txs == []

    def test_missing_columns(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.csv"
        bad.write_text("foo,bar\n1,2\n", encoding="utf-8")
        a = CSVAdapter(str(bad))
        assert a.get_transactions(date(2000, 1, 1)) == []


class TestFinTSAdapter:
    def test_connection_without_library(self) -> None:
        a = FinTSAdapter(blz="123", endpoint="https://example", username="u", pin="p", iban="DE1")
        # Ohne installiertes python-fints: False
        assert a.test_connection() is False

    def test_get_balances_returns_empty(self) -> None:
        a = FinTSAdapter(blz="1", endpoint="x", username="u", pin="p", iban="DE")
        assert a.get_balances() == []

    def test_get_transactions_returns_empty(self) -> None:
        a = FinTSAdapter(blz="1", endpoint="x", username="u", pin="p", iban="DE")
        assert a.get_transactions(date(2000, 1, 1)) == []
