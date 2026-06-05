"""Cashflow-Engine: berechnet monatliche Netto-Cashflows je Objekt.

Erkennt negative Cashflows — diese Information wird von der Event-Engine
als ``negative_object_cashflow``-Event aufgegriffen.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from app.config_loader import RealEstateAsset
from app.core.real_estate_model import simulate
from app.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MonthlyCashflow:
    year: int
    month: int
    rent: float
    operating_costs: float
    maintenance_reserve: float
    loan_payment: float  # Annuität (Zins + Tilgung)
    net_cashflow: float

    @property
    def is_negative(self) -> bool:
        return self.net_cashflow < 0


def monthly_cashflow(asset: RealEstateAsset, months: int) -> list[MonthlyCashflow]:
    """Erzeugt eine Cashflow-Liste über ``months`` Monate.

    Verwendet die Jahres-Snapshots aus :func:`simulate` und verteilt jeden
    Jahreswert gleichmäßig auf 12 Monate. Eine exaktere monatliche
    Betrachtung wäre möglich, ist hier aber nicht erforderlich — die
    Event-Engine reagiert auf Monatsschärfe, nicht auf Tagesgenauigkeit.
    """
    if months <= 0:
        return []
    years = (months + 11) // 12
    snapshots = simulate(asset, years)
    out: list[MonthlyCashflow] = []
    for snap in snapshots:
        monthly_rent = snap.rent_annual / 12.0
        monthly_op = snap.operating_costs_annual / 12.0
        monthly_reserve = snap.maintenance_reserve_annual / 12.0
        monthly_loan = (snap.interest_annual + snap.principal_annual) / 12.0
        for m in range(1, 13):
            if len(out) >= months:
                break
            net = monthly_rent - monthly_op - monthly_reserve - monthly_loan
            out.append(
                MonthlyCashflow(
                    year=snap.year,
                    month=m,
                    rent=round(monthly_rent, 2),
                    operating_costs=round(monthly_op, 2),
                    maintenance_reserve=round(monthly_reserve, 2),
                    loan_payment=round(monthly_loan, 2),
                    net_cashflow=round(net, 2),
                )
            )
    return out


def find_negative_cashflow_months(cashflows: Iterable[MonthlyCashflow]) -> list[MonthlyCashflow]:
    """Liefert die Monate mit negativem Netto-Cashflow."""
    return [c for c in cashflows if c.is_negative]


__all__ = ["MonthlyCashflow", "monthly_cashflow", "find_negative_cashflow_months"]
