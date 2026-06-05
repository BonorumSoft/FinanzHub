"""Tests für ``app.core.real_estate_model``."""

from __future__ import annotations

from app.config_loader import LoanConfig, RealEstateAsset
from app.core.real_estate_model import simulate


def _build_asset(**overrides: object) -> RealEstateAsset:
    defaults: dict = {
        "name": "Test",
        "current_value": 500_000,
        "purchase_price": 400_000,
        "value_growth": 0.02,
        "rent_monthly": 2_000,
        "rent_growth": 0.02,
        "operating_costs_monthly": 200,
        "maintenance_reserve_monthly": 150,
        "loan": LoanConfig(
            loan_remaining=100_000,
            interest_rate=0.035,
            loan_payment_monthly=1_200,
        ),
    }
    defaults.update(overrides)
    return RealEstateAsset.model_validate(defaults)


class TestAnnuity:
    def test_loan_decreases_every_month(self) -> None:
        """Restschuld muss Monat für Monat kleiner werden."""
        snaps = simulate(_build_asset(), years=3)
        assert len(snaps) == 3
        for prev, curr in zip(snaps, snaps[1:]):
            assert curr.loan_balance < prev.loan_balance

    def test_equity_increases_as_loan_decreases(self) -> None:
        """Eigenkapital (Wert - Restschuld) muss tendenziell steigen."""
        snaps = simulate(_build_asset(), years=10)
        for prev, curr in zip(snaps, snaps[1:]):
            assert curr.equity >= prev.equity

    def test_annuity_calculation_exact(self) -> None:
        """Referenzwert: 100.000 € @ 3,5 % p.a., Rate 1.200 €/Monat.

        Monat 1: Zinsen = 100000 * 0.035/12 = 291,67 €
                  Tilgung = 1200 - 291,67 = 908,33 €
                  Neue Restschuld = 99091,67 €
        """
        asset = _build_asset(
            current_value=200_000,
            purchase_price=200_000,
            rent_monthly=0,
            operating_costs_monthly=0,
            maintenance_reserve_monthly=0,
            loan=LoanConfig(loan_remaining=100_000, interest_rate=0.035, loan_payment_monthly=1_200),
        )
        # Wir simulieren 1 Jahr und prüfen Year 1: principal_annual ≈ 10 * 908,33 ≈ 9.083 €
        snaps = simulate(asset, years=1)
        assert len(snaps) == 1
        # Tilgung im ersten Jahr ≈ 908,33 * 12 = 10.900 €
        # Toleranz 5 %, da sich Zins mit der Restschuld ändert.
        assert 10_500 < snaps[0].principal_annual < 11_200
        # Zinsanteil Jahr 1 ≈ 291,67 * 12 - abnehmend
        assert 3_300 < snaps[0].interest_annual < 3_500

    def test_no_loan_no_errors(self) -> None:
        asset = _build_asset(loan=None)
        snaps = simulate(asset, years=3)
        assert all(snap.loan_balance == 0 for snap in snaps)
        assert all(snap.interest_annual == 0 for snap in snaps)

    def test_zero_years(self) -> None:
        assert simulate(_build_asset(), years=0) == []

    def test_value_growth(self) -> None:
        snaps = simulate(_build_asset(value_growth=0.0), years=3)
        assert snaps[2].property_value == snaps[0].property_value

    def test_rent_growth(self) -> None:
        snaps = simulate(_build_asset(rent_growth=0.10), years=2)
        # 10 % Wachstum pro Jahr → exakt 1.10
        ratio = snaps[1].rent_annual / snaps[0].rent_annual
        assert 1.099 < ratio < 1.101
