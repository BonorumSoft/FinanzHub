"""Tests für ``app.alerts.rent_matcher`` (Matching-Logik)."""

from __future__ import annotations

from datetime import date

import pytest

from app.alerts.rent_matcher import Transaction, match_all, match_tenant
from app.config_loader import MatchingConfig, TenantConfig


@pytest.fixture
def cfg() -> MatchingConfig:
    return MatchingConfig(standard_toleranz_euro=1.0, standard_toleranz_tage=5, warnung_ab_tag=3)


def _t(id_: str, day: int, amount: float, desc: str = "MIETE", iban: str | None = None) -> Transaction:
    return Transaction(
        id=id_,
        booking_date=date(2026, 6, day),
        amount=amount,
        description=desc,
        counterparty_iban=iban,
    )


class TestMatcher:
    def test_iban_match_takes_priority(self, cfg: MatchingConfig) -> None:
        t1 = _t("a", 3, 500, iban="DE111")
        t2 = _t("b", 3, 1000, iban="DE222", desc="OTHER TENANT")
        tenant = TenantConfig(
            name="A", iban="DE111", keyword="MIETE A", cold_rent_monthly=1000, expected_by_day=3
        )
        r = match_tenant(tenant, date(2026, 6, 1), [t1, t2], cfg)
        assert r.match_kind == "iban"
        assert r.matched_amount == 500.0
        assert r.status == "teilweise"

    def test_partial_payment_detected(self, cfg: MatchingConfig) -> None:
        t = _t("a", 3, 800, iban="DE111")
        tenant = TenantConfig(name="A", iban="DE111", cold_rent_monthly=1000, expected_by_day=3)
        r = match_tenant(tenant, date(2026, 6, 1), [t], cfg)
        assert r.status == "teilweise"

    def test_keyword_match(self, cfg: MatchingConfig) -> None:
        t = _t("a", 3, 1000, desc="MIETE A")
        tenant = TenantConfig(name="A", keyword="MIETE A", cold_rent_monthly=1000, expected_by_day=3)
        r = match_tenant(tenant, date(2026, 6, 1), [t], cfg)
        assert r.match_kind == "keyword"
        assert r.status == "bezahlt"

    def test_tolerance_window(self, cfg: MatchingConfig) -> None:
        # Tag 8 ist 5 Tage nach dem 3. → ok
        t = _t("a", 8, 1000, iban="DE111")
        tenant = TenantConfig(name="A", iban="DE111", cold_rent_monthly=1000, expected_by_day=3)
        r = match_tenant(tenant, date(2026, 6, 1), [t], cfg)
        assert r.status == "bezahlt"

    def test_out_of_window(self, cfg: MatchingConfig) -> None:
        t = _t("a", 15, 1000, iban="DE111")
        tenant = TenantConfig(name="A", iban="DE111", cold_rent_monthly=1000, expected_by_day=3)
        r = match_tenant(tenant, date(2026, 6, 1), [t], cfg)
        assert r.status == "offen"

    def test_claimed_not_available_for_others(self, cfg: MatchingConfig) -> None:
        t = _t("shared", 3, 1000, iban="DE_SHARED")
        a = TenantConfig(name="A", iban="DE_SHARED", cold_rent_monthly=1000, expected_by_day=3)
        b = TenantConfig(name="B", iban="DE_SHARED", cold_rent_monthly=1000, expected_by_day=3)
        results = match_all([a, b], date(2026, 6, 1), [t], cfg)
        assert results[0].status == "bezahlt"
        assert results[1].status == "offen"  # claimed by A

    def test_multiple_transactions(self, cfg: MatchingConfig) -> None:
        t1 = _t("a", 3, 500, iban="DE111")
        t2 = _t("b", 3, 500, iban="DE111")
        tenant = TenantConfig(name="A", iban="DE111", cold_rent_monthly=1000, expected_by_day=3)
        r = match_tenant(tenant, date(2026, 6, 1), [t1, t2], cfg)
        assert r.status == "bezahlt"
        assert len(r.matched_transactions) == 2

    def test_overpaid(self, cfg: MatchingConfig) -> None:
        t = _t("a", 3, 1100, iban="DE111")
        tenant = TenantConfig(name="A", iban="DE111", cold_rent_monthly=1000, expected_by_day=3)
        r = match_tenant(tenant, date(2026, 6, 1), [t], cfg)
        assert r.status == "zu_viel"
