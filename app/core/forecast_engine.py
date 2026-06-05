"""Forecast-Engine: mehrjährige Vermögensprojektion bis zum Renteneintritt.

Liquides Vermögen wächst mit ``market_return``. Immobilien werden Jahr
für Jahr via :func:`app.core.real_estate_model.simulate` projiziert.
Die Coverage Ratio setzt passive Einkünfte ins Verhältnis zu den
empfohlenen Entnahmen (``withdrawal_rate``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from app.config_loader import ForecastConfig, RealEstateAsset
from app.core.real_estate_model import YearlySnapshot, simulate
from app.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ForecastYear:
    year: int
    age: int
    liquid_assets: float
    real_estate_equity: float
    real_estate_value: float
    loan_balance_total: float
    total_wealth: float
    total_wealth_real: float
    rent_income_annual: float
    coverage_ratio: float
    snapshots: list[YearlySnapshot] = field(default_factory=list)


@dataclass
class ForecastResult:
    config: ForecastConfig
    starting_liquid: float
    starting_re_equity: float
    years: list[ForecastYear] = field(default_factory=list)
    final_wealth_nominal: float = 0.0
    final_wealth_real: float = 0.0
    retirement_reached: bool = False

    def to_table(self) -> list[list[str]]:
        rows: list[list[str]] = []
        rows.append(
            [
                "Jahr",
                "Alter",
                "Liquid (€)",
                "RE EK (€)",
                "Vermögen (€)",
                "Vermögen real (€)",
                "Mieteinn. (€)",
                "Coverage",
            ]
        )
        for y in self.years:
            rows.append(
                [
                    str(y.year),
                    str(y.age),
                    f"{y.liquid_assets:>14,.2f}",
                    f"{y.real_estate_equity:>14,.2f}",
                    f"{y.total_wealth:>14,.2f}",
                    f"{y.total_wealth_real:>14,.2f}",
                    f"{y.rent_income_annual:>14,.2f}",
                    f"{y.coverage_ratio:>6.2f}x",
                ]
            )
        return rows


def project(
    config: ForecastConfig,
    starting_liquid: float,
    assets: Iterable[RealEstateAsset],
) -> ForecastResult:
    """Projiziert das Vermögen ``config.current_age`` → ``retirement_age``."""
    years_to_project = max(0, config.retirement_age - config.current_age)
    if years_to_project == 0:
        logger.warning("current_age ist bereits >= retirement_age, leere Projektion")
        return ForecastResult(config=config, starting_liquid=starting_liquid, starting_re_equity=0.0)

    assets_list = list(assets)
    # Pro Immobilie eine jährliche Simulation
    per_asset_snapshots: list[list[YearlySnapshot]] = [simulate(a, years_to_project) for a in assets_list]
    starting_re_equity = sum(
        max(0.0, a.current_value - a.loan_balance()) for a in assets_list
    )

    result = ForecastResult(
        config=config,
        starting_liquid=starting_liquid,
        starting_re_equity=starting_re_equity,
    )
    liquid = starting_liquid
    inflation_discount = 1.0

    for year_idx in range(1, years_to_project + 1):
        liquid *= 1.0 + config.market_return
        inflation_discount *= 1.0 + config.inflation

        # Aggregation Immobilien
        re_value_total = 0.0
        loan_total = 0.0
        rent_total = 0.0
        snapshots_this_year: list[YearlySnapshot] = []
        for snaps in per_asset_snapshots:
            if year_idx <= len(snaps):
                s = snaps[year_idx - 1]
                re_value_total += s.property_value
                loan_total += s.loan_balance
                rent_total += s.rent_annual
                snapshots_this_year.append(s)
        re_equity = re_value_total - loan_total

        total_wealth = liquid + max(0.0, re_equity)
        total_wealth_real = total_wealth / inflation_discount

        # Coverage Ratio: passive Einkünfte / (Gesamtvermögen * withdrawal_rate / 12)
        monthly_withdrawal = total_wealth * config.withdrawal_rate / 12.0
        coverage_ratio = (
            rent_total / 12.0 / monthly_withdrawal if monthly_withdrawal > 0 else float("inf")
        )

        result.years.append(
            ForecastYear(
                year=year_idx,
                age=config.current_age + year_idx,
                liquid_assets=round(liquid, 2),
                real_estate_equity=round(max(0.0, re_equity), 2),
                real_estate_value=round(re_value_total, 2),
                loan_balance_total=round(loan_total, 2),
                total_wealth=round(total_wealth, 2),
                total_wealth_real=round(total_wealth_real, 2),
                rent_income_annual=round(rent_total, 2),
                coverage_ratio=round(coverage_ratio, 2)
                if not math_isinf(coverage_ratio)
                else 0.0,
                snapshots=snapshots_this_year,
            )
        )

    result.final_wealth_nominal = result.years[-1].total_wealth if result.years else 0.0
    result.final_wealth_real = result.years[-1].total_wealth_real if result.years else 0.0
    result.retirement_reached = True
    return result


def math_isinf(x: float) -> bool:
    """Kleine Hilfsfunktion, um den Import von math im Hauptcode zu vermeiden."""
    return x != x or x in (float("inf"), float("-inf"))


__all__ = ["ForecastResult", "ForecastYear", "project"]
