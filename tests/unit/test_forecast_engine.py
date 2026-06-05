"""Tests für ``app.core.forecast_engine``."""

from __future__ import annotations

from app.config_loader import ForecastConfig, LoanConfig, RealEstateAsset
from app.core.forecast_engine import project


def _asset(price: float = 500_000, loan: float = 250_000) -> RealEstateAsset:
    return RealEstateAsset.model_validate(
        {
            "name": "Test",
            "current_value": price,
            "purchase_price": price,
            "value_growth": 0.02,
            "rent_monthly": 2_000,
            "rent_growth": 0.02,
            "operating_costs_monthly": 200,
            "maintenance_reserve_monthly": 150,
            "loan": LoanConfig(loan_remaining=loan, interest_rate=0.035, loan_payment_monthly=1_200),
        }
    )


def _config(current_age: int = 35, retirement_age: int = 65) -> ForecastConfig:
    return ForecastConfig(
        current_age=current_age,
        retirement_age=retirement_age,
        market_return=0.07,
        inflation=0.02,
        withdrawal_rate=0.04,
    )


class TestForecast:
    def test_wealth_grows_with_market_return(self) -> None:
        """Liquides Vermögen muss nach 10 Jahren mit 7 % p.a. gewachsen sein.

        100.000 € * 1.07^10 ≈ 196.715 € (Compound Interest).
        """
        result = project(_config(current_age=30, retirement_age=40), starting_liquid=100_000, assets=[_asset()])
        assert len(result.years) == 10
        # 100.000 * 1.07^10 = 196.715,14 €
        assert 195_000 < result.years[-1].liquid_assets < 198_000

    def test_inflation_reduces_real_value(self) -> None:
        result = project(_config(), starting_liquid=100_000, assets=[])
        # Real-Wert < Nominalwert (Inflation 2 %)
        assert result.years[-1].total_wealth_real < result.years[-1].total_wealth

    def test_coverage_ratio_calculated(self) -> None:
        result = project(_config(), starting_liquid=500_000, assets=[_asset()])
        # Coverage Ratio > 0, wenn Mieteinnahmen > 0
        assert result.years[0].coverage_ratio > 0

    def test_retirement_at_exact_age(self) -> None:
        result = project(_config(current_age=35, retirement_age=65), starting_liquid=100_000, assets=[])
        assert len(result.years) == 30
        assert result.years[-1].age == 65

    def test_current_age_equals_retirement(self) -> None:
        result = project(_config(current_age=65, retirement_age=65), 100_000, [])
        assert result.years == []

    def test_immobilier_equity_grows(self) -> None:
        result = project(_config(), starting_liquid=0, assets=[_asset()])
        for prev, curr in zip(result.years, result.years[1:]):
            # Eigenkapital wächst (Wert steigt, Schulden sinken)
            assert curr.real_estate_equity >= prev.real_estate_equity - 1.0

    def test_coverage_ratio_zero_when_no_rent(self) -> None:
        asset = RealEstateAsset.model_validate(
            {
                "name": "X",
                "current_value": 1,
                "purchase_price": 1,
                "value_growth": 0,
                "rent_monthly": 0,
            }
        )
        result = project(_config(), starting_liquid=0, assets=[asset])
        assert result.years[0].coverage_ratio == 0.0
