"""Rent-Matching-Algorithmus.

Wird vom :class:`PaymentMonitor` und vom Mietabgleich-Event in der
Event-Engine verwendet. Implementiert die Spec-Logik:

1. IBAN-Treffer haben Vorrang vor Keyword-Treffern.
2. Zeitfenster: ``[zahltag - toleranz_tage, zahltag + toleranz_tage]``.
3. ``claimed``-Transaktionen stehen anderen Mietern nicht zur Verfügung.
4. Ergebnis-Status: ``bezahlt | teilweise | zu_viel | mehrfach | offen``.

Diese Logik wurde aus dem ursprünglichen Spec-Block in den
``payment_monitor`` extrahiert, damit sie sauber unit-testbar ist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.config_loader import MatchingConfig, TenantConfig
from app.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Transaction:
    """Minimaler, abstrahierter Transaktions-Datensatz für den Matcher."""

    id: str
    booking_date: date
    amount: float  # positiv = Eingang
    description: str
    counterparty_iban: str | None = None
    counterparty_name: str | None = None

    def claimed_by(self) -> str | None:
        """Lesezeichen, das der Matcher setzt; serialisierbar via dict."""
        return getattr(self, "_claimed_by", None)


@dataclass
class MatchResult:
    tenant: str
    expected_amount: float
    matched_transactions: list[Transaction] = field(default_factory=list)
    status: str = "offen"  # bezahlt | teilweise | zu_viel | mehrfach | offen
    matched_amount: float = 0.0
    match_kind: str | None = None  # "iban" | "keyword" | None

    @property
    def is_paid(self) -> bool:
        return self.status == "bezahlt"


def _normalize_iban(iban: str | None) -> str:
    return (iban or "").replace(" ", "").upper()


def _keyword_match(description: str, keyword: str) -> bool:
    if not keyword:
        return False
    return bool(re.search(re.escape(keyword), description, re.IGNORECASE))


def match_tenant(
    tenant: TenantConfig,
    period_month: date,
    transactions: list[Transaction],
    config: MatchingConfig,
    claimed_ids: set[str] | None = None,
) -> MatchResult:
    """Matched eine:n Mieter:in für den gegebenen Monat.

    ``period_month`` darf ein beliebiges Datum im Zielmonat sein — verwendet
    wird der ``expected_by_day`` zusammen mit ``config.standard_toleranz_tage``.
    """
    claimed = claimed_ids or set()
    result = MatchResult(
        tenant=tenant.name,
        expected_amount=tenant.cold_rent_monthly,
    )

    zahltag = period_month.replace(day=min(tenant.expected_by_day, 28))
    window_start = zahltag - timedelta(days=config.standard_toleranz_tage)
    window_end = zahltag + timedelta(days=config.standard_toleranz_tage)

    # Phase 1: IBAN-Match (hat Vorrang)
    iban_candidates: list[Transaction] = []
    if tenant.iban:
        norm = _normalize_iban(tenant.iban)
        for tx in transactions:
            if tx.id in claimed:
                continue
            if not (window_start <= tx.booking_date <= window_end):
                continue
            if _normalize_iban(tx.counterparty_iban) == norm:
                iban_candidates.append(tx)

    if iban_candidates:
        result.matched_transactions = iban_candidates
        result.match_kind = "iban"
    else:
        # Phase 2: Keyword-Match
        keyword_candidates: list[Transaction] = []
        if tenant.keyword:
            for tx in transactions:
                if tx.id in claimed:
                    continue
                if not (window_start <= tx.booking_date <= window_end):
                    continue
                if _keyword_match(tx.description, tenant.keyword):
                    keyword_candidates.append(tx)
        result.matched_transactions = keyword_candidates
        result.match_kind = "keyword" if keyword_candidates else None

    if not result.matched_transactions:
        return result

    result.matched_amount = round(sum(t.amount for t in result.matched_transactions), 2)
    diff = result.matched_amount - result.expected_amount
    abs_diff = abs(diff)
    if len(result.matched_transactions) > 1:
        # Mehrere Buchungen: Status hängt davon ab, ob die Summe stimmt.
        if abs_diff <= config.standard_toleranz_euro:
            result.status = "bezahlt"
        else:
            result.status = "mehrfach"
    else:
        if abs_diff <= config.standard_toleranz_euro:
            result.status = "bezahlt"
        elif diff < 0:
            result.status = "teilweise"
        else:
            result.status = "zu_viel"
    return result


def match_all(
    tenants: list[TenantConfig],
    period_month: date,
    transactions: list[Transaction],
    config: MatchingConfig,
) -> list[MatchResult]:
    """Matched alle Mieter:innen eines Zeitraums."""
    claimed: set[str] = set()
    results: list[MatchResult] = []
    for tenant in tenants:
        r = match_tenant(tenant, period_month, transactions, config, claimed)
        results.append(r)
        if r.status in ("bezahlt", "zu_viel", "mehrfach", "teilweise"):
            for tx in r.matched_transactions:
                claimed.add(tx.id)
    return results


__all__ = ["MatchResult", "Transaction", "match_all", "match_tenant"]
