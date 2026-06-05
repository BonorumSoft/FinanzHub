"""Neben-/Betriebskosten-Verteilung (NK-Abrechnung).

Unterstützt vier Verteilerschlüssel:

- ``wohnflaeche``: Anteilig zur Wohnfläche in m²
- ``einheiten``: Gleichmäßig pro Mieteinheit
- ``personen``: Anteilig zur Anzahl Personen im Haushalt
- ``verbrauch``: Nach Verbrauch (z. B. Heizöl, Wasser)

Pflichtprüfung am Ende: ``abs(sum(mieter_anteile) - jahreskosten) < 0.02``;
andernfalls wird ``NKValidationError`` ausgelöst.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum

from app.config_loader import OperatingCost, RealEstateAsset, TenantConfig
from app.logger import get_logger

logger = get_logger(__name__)


class NKValidationError(ValueError):
    """Wird ausgelöst, wenn die NK-Abrechnung die Summenprobe verletzt."""


class Verteilerschluessel(str, Enum):
    WOHNFLAECHE = "wohnflaeche"
    EINHEITEN = "einheiten"
    PERSONEN = "personen"
    VERBRAUCH = "verbrauch"


@dataclass
class NKResult:
    """Ergebnis einer NK-Abrechnung für ein Objekt pro Mieter."""

    asset_id: str
    year: int
    distribution_key: Verteilerschluessel
    total_costs: float
    per_tenant: dict[str, float] = field(default_factory=dict)
    umlagefaehig_per_tenant: dict[str, float] = field(default_factory=dict)
    nicht_umlagefaehig: float = 0.0
    details: dict[str, float] = field(default_factory=dict)


def _tenant_weight(tenant: TenantConfig, key: Verteilerschluessel) -> float:
    if key == Verteilerschluessel.WOHNFLAECHE:
        return tenant.wohnflaeche or 0.0
    if key == Verteilerschluessel.PERSONEN:
        return tenant.personen or 0
    if key == Verteilerschluessel.VERBRAUCH:
        return tenant.verbrauch_anteil or 0.0
    # EINHEITEN: jeder zählt 1, sofern er eine Einheit belegt
    return 1.0 if (tenant.unit_id or tenant.wohnflaeche) else 0.0


def _select_key(asset: RealEstateAsset) -> Verteilerschluessel:
    """Wählt den Verteilerschlüssel anhand der Tenant-Konfiguration."""
    tenants = asset.tenants
    if not tenants:
        return Verteilerschluessel.EINHEITEN
    if all(t.wohnflaeche for t in tenants):
        return Verteilerschluessel.WOHNFLAECHE
    if all(t.personen for t in tenants):
        return Verteilerschluessel.PERSONEN
    if all(t.verbrauch_anteil for t in tenants):
        return Verteilerschluessel.VERBRAUCH
    return Verteilerschluessel.EINHEITEN


def _operating_costs_total(costs: Iterable[OperatingCost]) -> tuple[float, float]:
    """Liefert (umlagefaehig_total, nicht_umlagefaehig_total) in EUR/Jahr."""
    uml = 0.0
    nicht = 0.0
    for c in costs:
        annual = c.amount_monthly * 12.0
        if c.umlagefaehig:
            uml += annual
        else:
            nicht += annual
    return uml, nicht


def distribute(asset: RealEstateAsset, year: int, key: Verteilerschluessel | None = None) -> NKResult:
    """Berechnet die NK-Anteile pro Mieter für das gegebene Jahr."""
    selected_key = key or _select_key(asset)
    uml_total, nicht_uml = _operating_costs_total(asset.operating_costs)
    # Wenn keine ``operating_costs`` gepflegt sind, fallen wir auf das
    # ``operating_costs_monthly``-Feld am Asset zurück.
    if not asset.operating_costs and asset.operating_costs_monthly:
        uml_total = asset.operating_costs_monthly * 12.0

    weights = {t.name: _tenant_weight(t, selected_key) for t in asset.tenants}
    weight_sum = sum(weights.values())

    per_tenant: dict[str, float] = {}
    umlagefaehig_pro_tenant: dict[str, float] = {}
    if weight_sum <= 0:
        # Fallback: gleichmäßig verteilen, falls keine Gewichtung möglich
        if asset.tenants:
            equal = uml_total / len(asset.tenants)
            for t in asset.tenants:
                per_tenant[t.name] = round(equal, 2)
                umlagefaehig_pro_tenant[t.name] = round(equal, 2)
    else:
        for tenant in asset.tenants:
            share = uml_total * weights[tenant.name] / weight_sum
            per_tenant[tenant.name] = round(share, 2)
            umlagefaehig_pro_tenant[tenant.name] = round(share, 2)

    result = NKResult(
        asset_id=asset.id or asset.name,
        year=year,
        distribution_key=selected_key,
        total_costs=round(uml_total + nicht_uml, 2),
        per_tenant=per_tenant,
        umlagefaehig_per_tenant=umlagefaehig_pro_tenant,
        nicht_umlagefaehig=round(nicht_uml, 2),
    )
    _validate_summenprobe(result, uml_total)
    logger.info(
        "NK %s/Jahr %d: %.2f € verteilt (%s) auf %d Mieter",
        asset.name,
        year,
        uml_total,
        selected_key.value,
        len(asset.tenants),
    )
    return result


def _validate_summenprobe(result: NKResult, total_umlagefaehig: float) -> None:
    """Stellt sicher, dass die Mieteranteile zu den Gesamtkosten passen."""
    sum_anteile = sum(result.umlagefaehig_per_tenant.values())
    differenz = abs(sum_anteile - total_umlagefaehig)
    if differenz > 0.02:
        raise NKValidationError(
            f"Summenprobe verletzt für {result.asset_id}/{result.year}: "
            f"sum={sum_anteile:.4f}, expected={total_umlagefaehig:.4f}, "
            f"|diff|={differenz:.4f}"
        )


__all__ = [
    "NKResult",
    "NKValidationError",
    "Verteilerschluessel",
    "distribute",
]
