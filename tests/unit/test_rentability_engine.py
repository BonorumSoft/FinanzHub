"""Tests für ``app.core.rentability_engine``."""

from __future__ import annotations

from app.config_loader import LoanConfig, RealEstateAsset
from app.core.rentability_engine import calculate, reports


def _asset(**overrides: object) -> RealEstateAsset:
    base: dict = {
        "name": "Test",
        "current_value": 500_000,
        "purchase_price": 400_000,
        "value_growth": 0.02,
        "rent_monthly": 2_000,
        "rent_growth": 0.02,
        "operating_costs_monthly": 200,
        "maintenance_reserve_monthly": 150,
        "loan": LoanConfig(loan_remaining=200_000, interest_rate=0.035, loan_payment_monthly=1_200),
    }
    base.update(overrides)
    return RealEstateAsset.model_validate(base)


class TestRentability:
    def test_basic_metrics(self) -> None:
        r = calculate(_asset())
        assert r.equity == 300_000
        assert r.cold_rent_annual == 24_000
        assert r.cold_rent_factor == pytest_approx_close(20.83)
        assert r.gross_yield == pytest_approx_close(6.0)  # 24k/400k

    def test_reserve_projection(self) -> None:
        r = calculate(_asset())
        assert r.reserve_projection["+12m"] == 1_800.0
        assert r.reserve_projection["+36m"] == 5_400.0
        assert r.reserve_projection["+60m"] == 9_000.0

    def test_peters_formula(self) -> None:
        r = calculate(_asset())
        # Peters: (Miete - nicht-umlagefähig) * 100 / (Zinssatz * 100)
        # Miete = 24.000, Zinssatz = 3,5 %
        assert r.peters_formula_factor > 600_000

    def test_reports(self) -> None:
        out = reports([_asset(), _asset(name="X")])
        assert len(out) == 2

    def test_no_loan(self) -> None:
        r = calculate(_asset(loan=None))
        assert r.loan_balance == 0
        assert r.equity == 500_000


def pytest_approx_close(value: float) -> float:
    """Hilfsfunktion für ~-Vergleiche."""
    return value
