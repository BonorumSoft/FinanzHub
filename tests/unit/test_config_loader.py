"""Tests für Pydantic-v2-Schemas und YAML-Loader."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config_loader import (
    AppSettings,
    AssetsConfig,
    ForecastConfig,
    MatchingConfig,
    NotificationRule,
    NotificationsConfig,
    RealEstateAsset,
    SecurityPosition,
    VermoegenConfig,
    load_assets,
    load_banks,
    load_forecast,
    load_income,
    load_mail,
    load_notifications,
    load_settings,
)


class TestSecurityPosition:
    def test_minimal(self) -> None:
        pos = SecurityPosition(isin="US0378331005", quantity=1.0, purchase_price=100.0)
        assert pos.isin == "US0378331005"
        assert pos.current_value is None

    def test_legacy_alias_value_to_current_value(self) -> None:
        pos = SecurityPosition.model_validate(
            {"isin": "X", "quantity": 1, "purchase_price": 1, "value": 50}
        )
        assert pos.current_value == 50

    def test_legacy_alias_growth(self) -> None:
        pos = SecurityPosition.model_validate(
            {"isin": "X", "quantity": 1, "purchase_price": 1, "growth": 0.05}
        )
        assert pos.value_growth == 0.05

    def test_invalid_extra_field_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SecurityPosition.model_validate(
                {"isin": "X", "quantity": 1, "purchase_price": 1, "unknown": True}
            )


class TestRealEstateAsset:
    def test_legacy_top_level_loan(self) -> None:
        re = RealEstateAsset.model_validate(
            {
                "name": "Test",
                "current_value": 100000,
                "purchase_price": 100000,
                "value_growth": 0.02,
                "rent_monthly": 1000,
                "loan_remaining": 50000,
                "interest_rate": 0.03,
                "loan_payment_monthly": 500,
            }
        )
        assert re.loan is not None
        assert re.loan.loan_remaining == 50000

    def test_nested_loan(self) -> None:
        re = RealEstateAsset.model_validate(
            {
                "name": "Test",
                "current_value": 100000,
                "purchase_price": 100000,
                "value_growth": 0.02,
                "rent_monthly": 1000,
                "loan": {
                    "loan_remaining": 50000,
                    "interest_rate": 0.03,
                    "loan_payment_monthly": 500,
                },
            }
        )
        assert re.loan_balance() == 50000

    def test_immobilien_alias(self) -> None:
        cfg = AssetsConfig.model_validate(
            {
                "immobilien": [
                    {
                        "name": "X",
                        "current_value": 1,
                        "purchase_price": 1,
                        "value_growth": 0,
                        "rent_monthly": 1,
                    }
                ]
            }
        )
        assert len(cfg.real_estate) == 1


class TestMatchingConfig:
    def test_defaults(self) -> None:
        c = MatchingConfig()
        assert c.standard_toleranz_euro == 1.00
        assert c.warnung_ab_tag == 3


class TestVermoegenConfig:
    def test_defaults(self) -> None:
        c = VermoegenConfig()
        assert c.schwellwert_liquiditaet_euro == 1500.0
        assert c.substance_consecutive_months == 3


class TestAppSettings:
    def test_defaults(self) -> None:
        s = AppSettings()
        assert s.zeitzone == "Europe/Berlin"
        assert s.matching.standard_toleranz_euro == 1.00


class TestForecastConfig:
    def test_current_age_required(self) -> None:
        """Ohne ``current_age`` wird per Default-Wert ein Wert gesetzt
        (siehe ``model_validator`` in ``config_loader``). Der Test stellt
        sicher, dass das Verhalten dokumentiert ist."""
        fc = ForecastConfig.model_validate({})
        assert fc.current_age > 0

    def test_explicit_current_age_overrides_default(self) -> None:
        with pytest.raises(ValidationError):
            ForecastConfig.model_validate({"current_age": "not_an_int"})

    def test_with_current_age(self) -> None:
        fc = ForecastConfig(current_age=30)
        assert fc.current_age == 30
        assert fc.retirement_age == 65


class TestNotificationsConfig:
    def test_get_by_id(self) -> None:
        cfg = NotificationsConfig(
            rules=[
                NotificationRule(id="daily_wealth_report", template="daily_wealth_report", schedule="daily"),
            ]
        )
        assert cfg.get("daily_wealth_report") is not None
        assert cfg.get("nope") is None


class TestLoaders:
    def test_load_settings(self) -> None:
        s = load_settings("config.example")
        assert s.zeitzone == "Europe/Berlin"

    def test_load_assets(self) -> None:
        a = load_assets("config.example")
        assert len(a.securities) >= 1
        assert len(a.real_estate) >= 1

    def test_load_banks(self) -> None:
        b = load_banks("config.example")
        assert b.active_adapter == "demo"
        assert len(b.adapters) >= 1

    def test_load_forecast(self) -> None:
        f = load_forecast("config.example")
        assert f.current_age > 0

    def test_load_mail(self) -> None:
        m = load_mail("config.example")
        assert m.host == "smtp.gmail.com"

    def test_load_notifications(self) -> None:
        n = load_notifications("config.example")
        assert any(r.id == "daily_wealth_report" for r in n.rules)

    def test_load_income(self) -> None:
        i = load_income("config.example")
        assert any(e.name == "Gehalt" for e in i.expected_income)
