"""Immobilien-Simulationsmodell.

Simuliert eine einzelne Immobilie Jahr für Jahr. Die Annuitätenrechnung
ist exakt (keine Näherung): jeden Monat wird der Tilgungsanteil berechnet
und von der Restschuld abgezogen, der Zinsanteil fließt in den Cashflow.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.config_loader import RealEstateAsset
from app.logger import get_logger

logger = get_logger(__name__)


@dataclass
class YearlySnapshot:
    """Jahresscheibe einer Immobilien-Simulation."""

    year: int
    property_value: float
    loan_balance: float
    equity: float
    rent_annual: float
    operating_costs_annual: float
    maintenance_reserve_annual: float
    interest_annual: float
    principal_annual: float
    net_cashflow_annual: float
    cold_rent_factor: float  # property_value / rent_annual


def simulate(asset: RealEstateAsset, years: int) -> list[YearlySnapshot]:
    """Simuliert ``asset`` über ``years`` Jahre.

    Verwendet eine exakte monatliche Annuitätenrechnung. Die
    Monatsschleife iteriert 12-mal pro Jahr, akkumuliert Zins- und
    Tilgungsanteile, und schreibt am Jahresende einen :class:`YearlySnapshot`.
    """
    if years <= 0:
        return []

    snapshots: list[YearlySnapshot] = []
    value = asset.current_value
    rent_monthly = asset.rent_monthly
    loan = asset.loan_balance()
    monthly_rate = asset.loan.interest_rate / 12.0 if asset.loan else 0.0
    payment = asset.loan.loan_payment_monthly if asset.loan else 0.0

    op_costs = asset.operating_costs_monthly
    reserve = asset.maintenance_reserve_monthly

    for year_idx in range(1, years + 1):
        # Wertentwicklung und Mietentwicklung sind jährliche Multiplikatoren
        value *= 1.0 + asset.value_growth
        rent_monthly *= 1.0 + asset.rent_growth

        # 12-Monats-Schleife für die Annuität
        interest_year = 0.0
        principal_year = 0.0
        for _ in range(12):
            if loan <= 0 or payment <= 0:
                break
            interest = loan * monthly_rate
            principal = payment - interest
            if principal > loan:
                principal = loan
                # Letzte Rate: Zins + Tilgung = Restschuld
                interest = max(0.0, loan * monthly_rate)
            loan -= principal
            interest_year += interest
            principal_year += principal

        rent_annual = rent_monthly * 12.0
        op_annual = op_costs * 12.0
        reserve_annual = reserve * 12.0
        kapitaldienst = interest_year + principal_year
        net_cashflow = rent_annual - op_annual - reserve_annual - kapitaldienst
        equity = max(0.0, value - max(loan, 0.0))
        cold_rent_factor = value / rent_annual if rent_annual > 0 else float("inf")

        snapshots.append(
            YearlySnapshot(
                year=year_idx,
                property_value=round(value, 2),
                loan_balance=round(max(loan, 0.0), 2),
                equity=round(equity, 2),
                rent_annual=round(rent_annual, 2),
                operating_costs_annual=round(op_annual, 2),
                maintenance_reserve_annual=round(reserve_annual, 2),
                interest_annual=round(interest_year, 2),
                principal_annual=round(principal_year, 2),
                net_cashflow_annual=round(net_cashflow, 2),
                cold_rent_factor=round(cold_rent_factor, 2),
            )
        )

    return snapshots


def total_equity_now(assets: Iterable[RealEstateAsset]) -> float:
    """Liefert die Summe aller aktuellen Eigenkapital-Anteile."""
    total = 0.0
    for a in assets:
        total += max(0.0, a.current_value - a.loan_balance())
    return total


def total_rent_annual(assets: Iterable[RealEstateAsset]) -> float:
    return sum(a.rent_monthly * 12.0 for a in assets)


__all__ = ["YearlySnapshot", "simulate", "total_equity_now", "total_rent_annual"]
