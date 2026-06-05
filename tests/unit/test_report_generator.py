"""Tests für ``app.output.report_generator``."""

from __future__ import annotations

from datetime import date

from app.alerts.payment_monitor import IncomeCheckResult
from app.alerts.rent_matcher import MatchResult
from app.config_loader import AppSettings, LoanConfig, RealEstateAsset
from app.core.forecast_engine import project
from app.core.portfolio_engine import NetWorth, RealEstateDetail, SecurityValuation
from app.core.rentability_engine import calculate
from app.output.report_generator import (
    cashflow_table,
    forecast_table,
    income_table,
    positions_table,
    rent_matrix_table,
    rentability_table,
    wealth_table,
)


def _nw() -> NetWorth:
    return NetWorth(
        bank_total=1000.0,
        securities_total=2000.0,
        real_estate_equity=5000.0,
        net_worth=8000.0,
        calculated_at=date(2026, 6, 15),
        positions=[
            SecurityValuation(
                isin="X",
                name="X",
                quantity=1.0,
                purchase_price=100.0,
                current_price=150.0,
                value=150.0,
                pnl=50.0,
                pnl_percent=50.0,
            )
        ],
        real_estate_details=[
            RealEstateDetail(name="A", current_value=500_000, loan_balance=200_000, equity=300_000, equity_ratio=60.0)
        ],
        bank_accounts=[],
    )


class TestReportGenerator:
    def test_wealth_table(self) -> None:
        out = wealth_table(_nw())
        assert "Nettovermögen" in out
        assert "8,000.00" in out

    def test_positions_table(self) -> None:
        out = positions_table(_nw())
        assert "X" in out
        assert "150.00" in out

    def test_positions_table_empty(self) -> None:
        empty = NetWorth(
            bank_total=0, securities_total=0, real_estate_equity=0, net_worth=0, calculated_at=date.today(), positions=[]
        )
        assert positions_table(empty) == "(keine Positionen)"

    def test_rent_matrix_table(self) -> None:
        result = MatchResult(tenant="A", expected_amount=1000.0, matched_amount=1000.0, status="bezahlt", match_kind="iban")
        out = rent_matrix_table([result], "2026-06")
        # Tenant-Name wird in der psql-Tabelle auf 7 Zeichen gekürzt
        assert "bezahlt" in out
        assert "iban" in out
        assert "2026-06" in out

    def test_income_table(self) -> None:
        r = IncomeCheckResult(name="Gehalt", expected_amount_min=3000.0, matched_amount=3500.0, status="bezahlt", matched_transactions=[])
        out = income_table([r])
        assert "Gehalt" in out

    def test_rentability_table(self) -> None:
        asset = RealEstateAsset.model_validate(
            {
                "name": "X",
                "current_value": 500_000,
                "purchase_price": 400_000,
                "value_growth": 0.02,
                "rent_monthly": 2_000,
                "loan": LoanConfig(loan_remaining=200_000, interest_rate=0.035, loan_payment_monthly=1_200),
            }
        )
        out = rentability_table([calculate(asset)])
        assert "X" in out
        assert "Brutto" in out

    def test_cashflow_table(self) -> None:
        from app.core.cashflow_engine import monthly_cashflow

        asset = RealEstateAsset.model_validate(
            {
                "name": "X",
                "current_value": 1,
                "purchase_price": 1,
                "value_growth": 0,
                "rent_monthly": 1000,
            }
        )
        out = cashflow_table(monthly_cashflow(asset, months=3))
        assert "Netto" in out
        assert "Monat" in out

    def test_forecast_table(self) -> None:
        fc = AppSettings()
        from app.config_loader import ForecastConfig

        result = project(ForecastConfig(current_age=30, retirement_age=33), 100_000, [])
        out = forecast_table(result)
        assert "Jahr" in out
        assert "Liquid" in out
