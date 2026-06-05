"""Tests für ``app.core.nk_calculator``."""

from __future__ import annotations

from app.config_loader import OperatingCost, RealEstateAsset, TenantConfig
from app.core.nk_calculator import Verteilerschluessel, distribute


def _asset(tenants: list[TenantConfig], costs: list[OperatingCost] | None = None) -> RealEstateAsset:
    return RealEstateAsset.model_validate(
        {
            "name": "Test",
            "current_value": 1,
            "purchase_price": 1,
            "value_growth": 0,
            "rent_monthly": 0,
            "tenants": [t.model_dump() for t in tenants],
            "operating_costs": [c.model_dump() for c in (costs or [])],
        }
    )


def _tenant(name: str, wfl: float = 80.0) -> TenantConfig:
    return TenantConfig(name=name, wohnflaeche=wfl)


class TestNKCalculator:
    def test_wohnflaeche_key_sums_to_total(self) -> None:
        asset = _asset(
            [_tenant("A", 80), _tenant("B", 80)],
            [
                OperatingCost(name="V", amount_monthly=100, umlagefaehig=True),
            ],
        )
        result = distribute(asset, year=2026, key=Verteilerschluessel.WOHNFLAECHE)
        assert abs(sum(result.per_tenant.values()) - 1200.0) < 0.02

    def test_einheiten_key_equal_distribution(self) -> None:
        a = TenantConfig(name="A", unit_id="U1")
        b = TenantConfig(name="B", unit_id="U2")
        asset = _asset([a, b], [OperatingCost(name="X", amount_monthly=120, umlagefaehig=True)])
        result = distribute(asset, year=2026, key=Verteilerschluessel.EINHEITEN)
        assert result.per_tenant["A"] == result.per_tenant["B"]
        assert abs(result.per_tenant["A"] - 720.0) < 0.02

    def test_personen_key(self) -> None:
        a = TenantConfig(name="A", personen=2)
        b = TenantConfig(name="B", personen=1)
        asset = _asset([a, b], [OperatingCost(name="X", amount_monthly=120, umlagefaehig=True)])
        result = distribute(asset, year=2026, key=Verteilerschluessel.PERSONEN)
        # A: 2/3 * 1440 = 960, B: 1/3 * 1440 = 480
        assert abs(result.per_tenant["A"] - 960.0) < 0.02
        assert abs(result.per_tenant["B"] - 480.0) < 0.02

    def test_summenprobe_passes(self) -> None:
        """Bei 0,01 € Differenz darf keine Exception fliegen."""
        asset = _asset(
            [_tenant("A", 70), _tenant("B", 30)],
            [OperatingCost(name="X", amount_monthly=123.45, umlagefaehig=True)],
        )
        distribute(asset, year=2026)  # should not raise

    def test_auto_selects_wohnflaeche_when_available(self) -> None:
        asset = _asset(
            [_tenant("A", 50), _tenant("B", 50)],
            [OperatingCost(name="X", amount_monthly=100, umlagefaehig=True)],
        )
        result = distribute(asset, year=2026)
        assert result.distribution_key == Verteilerschluessel.WOHNFLAECHE

    def test_non_umlagefaehig_kept_apart(self) -> None:
        asset = _asset(
            [_tenant("A", 50), _tenant("B", 50)],
            [
                OperatingCost(name="Umlage", amount_monthly=100, umlagefaehig=True),
                OperatingCost(name="Verwaltung", amount_monthly=50, umlagefaehig=False),
            ],
        )
        result = distribute(asset, year=2026)
        assert result.nicht_umlagefaehig == 600.0
        assert abs(sum(result.umlagefaehig_per_tenant.values()) - 1200.0) < 0.02
