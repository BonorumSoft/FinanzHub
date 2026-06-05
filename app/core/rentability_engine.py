"""Rentabilitäts-Kennzahlen für einzelne Immobilien.

Berechnet alle gängigen Immobilien-KPIs inkl. Rücklagen-Hochrechnung und
der Petersschen Formel (Vervielfältiger).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field

from app.config_loader import RealEstateAsset
from app.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RentabilityReport:
    asset_id: str
    name: str
    current_value: float
    loan_balance: float
    equity: float
    equity_ratio: float  # EK / Kaufpreis %
    cold_rent_annual: float
    cold_rent_factor: float  # Kaufpreis / Jahresnettokaltmiete
    gross_yield: float  # Jahresnettokaltmiete / Kaufpreis %
    net_yield: float  # (Miete - nicht-umlagefähige Kosten) / Kaufpreis %
    rental_risk_factor: float  # EK / Jahresnettokaltmiete
    reserve_projection: dict[str, float] = field(default_factory=dict)
    peters_formula_factor: float = 0.0


def _annual_non_umlagefaehig(asset: RealEstateAsset) -> float:
    return sum(
        c.amount_monthly * 12.0 for c in asset.operating_costs if not c.umlagefaehig
    )


def calculate(asset: RealEstateAsset) -> RentabilityReport:
    """Berechnet den Kennzahlen-Report für ein einzelnes Objekt."""
    cold_rent_annual = asset.rent_monthly * 12.0
    equity = max(0.0, asset.current_value - asset.loan_balance())
    equity_ratio = (equity / asset.purchase_price * 100.0) if asset.purchase_price else 0.0
    gross_yield = (cold_rent_annual / asset.purchase_price * 100.0) if asset.purchase_price else 0.0
    nicht_uml = _annual_non_umlagefaehig(asset)
    net_yield = (
        (cold_rent_annual - nicht_uml) / asset.purchase_price * 100.0
        if asset.purchase_price
        else 0.0
    )
    cold_rent_factor = (
        asset.current_value / cold_rent_annual if cold_rent_annual > 0 else math.inf
    )
    rental_risk_factor = equity / cold_rent_annual if cold_rent_annual > 0 else math.inf

    # Rücklagen-Hochrechnung
    reserve_projection = {
        "+12m": round(asset.maintenance_reserve_monthly * 12.0, 2),
        "+36m": round(asset.maintenance_reserve_monthly * 36.0, 2),
        "+60m": round(asset.maintenance_reserve_monthly * 60.0, 2),
    }

    # Peterssche Formel (vereinfachte Variante):
    # Vervielfältiger = (Mieteinnahme - nicht-umlagefähige Kosten) * 100 / Zinssatz
    interest_rate = asset.loan.interest_rate if asset.loan else 0.04
    if interest_rate > 0:
        peters = (cold_rent_annual - nicht_uml) * 100.0 / (interest_rate * 100.0)
    else:
        peters = math.inf
    peters = round(peters, 2) if not math.isinf(peters) else 0.0

    return RentabilityReport(
        asset_id=asset.id or asset.name,
        name=asset.name,
        current_value=asset.current_value,
        loan_balance=asset.loan_balance(),
        equity=round(equity, 2),
        equity_ratio=round(equity_ratio, 2),
        cold_rent_annual=round(cold_rent_annual, 2),
        cold_rent_factor=round(cold_rent_factor, 2),
        gross_yield=round(gross_yield, 2),
        net_yield=round(net_yield, 2),
        rental_risk_factor=round(rental_risk_factor, 2),
        reserve_projection=reserve_projection,
        peters_formula_factor=peters,
    )


def reports(assets: Iterable[RealEstateAsset]) -> list[RentabilityReport]:
    """Berechnet Reports für eine Liste von Immobilien."""
    return [calculate(a) for a in assets]


__all__ = ["RentabilityReport", "calculate", "reports"]
