"""Payment-Monitor: prüft Mieteingänge (Objekte) und manuelle
Einkommenserwartungen (Gehalt etc.) gegen tatsächliche Buchungen.

Verwendet die Matching-Logik aus :mod:`app.alerts.rent_matcher`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy.engine import Engine

from app.alerts.rent_matcher import (
    MatchResult,
    Transaction,
    match_all,
)
from app.config_loader import AssetsConfig, ExpectedIncome, IncomeConfig, MatchingConfig
from app.data.db import execute
from app.logger import get_logger

logger = get_logger(__name__)


@dataclass
class IncomeCheckResult:
    name: str
    expected_amount_min: float
    matched_amount: float
    status: str
    matched_transactions: list[Transaction]


def _fetch_transactions(engine: Engine, start: date, end: date) -> list[Transaction]:
    rows = execute(
        engine,
        "SELECT transaction_id AS id, booking_date, amount, description, "
        "counterparty_iban, counterparty_name "
        "FROM transactions "
        "WHERE booking_date BETWEEN :s AND :e AND amount > 0 AND is_internal = FALSE",
        {"s": start.isoformat(), "e": end.isoformat()},
    )
    out: list[Transaction] = []
    for r in rows:
        bd = r["booking_date"]
        if isinstance(bd, str):
            from datetime import datetime

            bd = datetime.fromisoformat(bd).date()
        out.append(
            Transaction(
                id=r["id"],
                booking_date=bd,
                amount=float(r["amount"]),
                description=r.get("description") or "",
                counterparty_iban=r.get("counterparty_iban"),
                counterparty_name=r.get("counterparty_name"),
            )
        )
    return out


def check_rent(
    engine: Engine,
    assets: AssetsConfig,
    period_month: date,
    matching_config: MatchingConfig,
) -> list[MatchResult]:
    """Prüft die Mieteingänge aller Objekte für ``period_month``."""
    start = period_month.replace(day=1)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1, day=1)
    else:
        end = start.replace(month=start.month + 1, day=1)
    transactions = _fetch_transactions(engine, start, end)
    results: list[MatchResult] = []
    for asset in assets.real_estate:
        results.extend(match_all(asset.tenants, period_month, transactions, matching_config))
    return results


def check_income(
    engine: Engine,
    income_config: IncomeConfig,
    period_month: date,
) -> list[IncomeCheckResult]:
    """Prüft manuelle Einkommenserwartungen (Gehalt etc.)."""
    start = period_month.replace(day=1)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1, day=1)
    else:
        end = start.replace(month=start.month + 1, day=1)
    transactions = _fetch_transactions(engine, start, end)
    results: list[IncomeCheckResult] = []
    for exp in income_config.expected_income:
        matched = _match_income(exp, transactions)
        status = "bezahlt" if matched else "offen"
        results.append(
            IncomeCheckResult(
                name=exp.name,
                expected_amount_min=exp.amount_min,
                matched_amount=sum(t.amount for t in matched),
                status=status,
                matched_transactions=matched,
            )
        )
    return results


def _match_income(exp: ExpectedIncome, transactions: list[Transaction]) -> list[Transaction]:
    out: list[Transaction] = []
    for tx in transactions:
        if tx.amount < exp.amount_min:
            continue
        if exp.keywords and not any(k.lower() in tx.description.lower() for k in exp.keywords):
            continue
        out.append(tx)
    return out


__all__ = ["IncomeCheckResult", "check_income", "check_rent"]
