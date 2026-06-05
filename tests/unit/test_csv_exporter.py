"""Tests für ``app.output.csv_exporter``."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from app.core.portfolio_engine import NetWorth, SecurityValuation
from app.output.csv_exporter import export_networth, export_transactions


def _nw() -> NetWorth:
    return NetWorth(
        bank_total=100.0,
        securities_total=200.0,
        real_estate_equity=300.0,
        net_worth=600.0,
        calculated_at=date(2026, 6, 15),
        positions=[
            SecurityValuation(
                isin="US0378331005",
                name="AAPL",
                quantity=1.0,
                purchase_price=100.0,
                current_price=150.0,
                value=150.0,
                pnl=50.0,
                pnl_percent=50.0,
            )
        ],
        real_estate_details=[],
        bank_accounts=[],
    )


class TestCsvExporter:
    def test_export_networth(self, tmp_path: Path) -> None:
        out = export_networth(_nw(), tmp_path)
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "net_worth" in content
        assert "US0378331005" in content

    def test_export_networth_empty(self, tmp_path: Path) -> None:
        empty = NetWorth(
            bank_total=0,
            securities_total=0,
            real_estate_equity=0,
            net_worth=0,
            calculated_at=date.today(),
            positions=[],
        )
        out = export_networth(empty, tmp_path)
        assert out.exists()

    def test_export_transactions(self, tmp_path: Path) -> None:
        rows = [
            {"id": "1", "amount": 100.0, "description": "X"},
            {"id": "2", "amount": -50.0, "description": "Y"},
        ]
        out = export_transactions(rows, tmp_path)
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "amount" in content
        assert "X" in content

    def test_export_transactions_empty(self, tmp_path: Path) -> None:
        out = export_transactions([], tmp_path)
        assert out.exists()
        assert out.read_text(encoding="utf-8") == ""
