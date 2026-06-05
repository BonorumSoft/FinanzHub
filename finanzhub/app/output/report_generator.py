"""Report-Generator: erzeugt formatierte Tabellen und Übersichten
für die CLI und die Notification-Engine.
"""

from __future__ import annotations

from collections.abc import Iterable

from tabulate import tabulate

from app.alerts.payment_monitor import IncomeCheckResult
from app.alerts.rent_matcher import MatchResult
from app.core.cashflow_engine import MonthlyCashflow
from app.core.forecast_engine import ForecastResult
from app.core.portfolio_engine import NetWorth
from app.core.rentability_engine import RentabilityReport
from app.logger import get_logger

logger = get_logger(__name__)


def wealth_table(nw: NetWorth) -> str:
    rows = [
        ["Bankguthaben", f"{nw.bank_total:>14,.2f} €"],
        ["Depot", f"{nw.securities_total:>14,.2f} €"],
        ["Immobilien-Eigenkapital", f"{nw.real_estate_equity:>14,.2f} €"],
        ["—", "—"],
        ["Nettovermögen", f"{nw.net_worth:>14,.2f} €"],
    ]
    return tabulate(rows, headers=["Position", "Wert"], tablefmt="psql")


def positions_table(nw: NetWorth) -> str:
    if not nw.positions:
        return "(keine Positionen)"
    rows = [
        [
            p.isin,
            p.name or "—",
            f"{p.quantity:.2f}",
            f"{p.current_price:.2f} €",
            f"{p.value:,.2f} €",
            f"{p.pnl:,.2f} €",
            f"{p.pnl_percent:.2f} %",
        ]
        for p in nw.positions
    ]
    return tabulate(
        rows,
        headers=["ISIN", "Name", "Menge", "Kurs", "Wert", "P&L", "P&L %"],
        tablefmt="psql",
    )


def rent_matrix_table(results: Iterable[MatchResult], period: str) -> str:
    rows = [
        [
            r.tenant,
            f"{r.expected_amount:>10,.2f} €",
            f"{r.matched_amount:>10,.2f} €",
            r.status,
            r.match_kind or "—",
        ]
        for r in results
    ]
    return tabulate(
        rows,
        headers=[f"Mieter · {period}", "Erwartet", "Eingegangen", "Status", "Match"],
        tablefmt="psql",
    )


def income_table(results: Iterable[IncomeCheckResult]) -> str:
    rows = [
        [
            r.name,
            f"{r.expected_amount_min:>10,.2f} €",
            f"{r.matched_amount:>10,.2f} €",
            r.status,
        ]
        for r in results
    ]
    return tabulate(
        rows,
        headers=["Erwartung", "Mindestbetrag", "Erhalten", "Status"],
        tablefmt="psql",
    )


def rentability_table(reports: Iterable[RentabilityReport]) -> str:
    rows = [
        [
            r.name,
            f"{r.current_value:>12,.0f} €",
            f"{r.equity:>12,.0f} €",
            f"{r.equity_ratio:>5.1f} %",
            f"{r.gross_yield:>5.2f} %",
            f"{r.net_yield:>5.2f} %",
            f"{r.cold_rent_factor:>6.2f}x",
        ]
        for r in reports
    ]
    return tabulate(
        rows,
        headers=["Objekt", "Wert", "EK", "EK %", "Brutto", "Netto", "Faktor"],
        tablefmt="psql",
    )


def cashflow_table(cashflows: Iterable[MonthlyCashflow]) -> str:
    rows = [
        [
            f"{c.year:04d}-{c.month:02d}",
            f"{c.rent:>10,.2f} €",
            f"{c.operating_costs:>10,.2f} €",
            f"{c.maintenance_reserve:>10,.2f} €",
            f"{c.loan_payment:>10,.2f} €",
            f"{c.net_cashflow:>10,.2f} €",
        ]
        for c in cashflows
    ]
    return tabulate(
        rows,
        headers=["Monat", "Miete", "Op.-Kosten", "Rücklage", "Kapitaldienst", "Netto"],
        tablefmt="psql",
    )


def forecast_table(forecast: ForecastResult) -> str:
    return tabulate(forecast.to_table(), headers="firstrow", tablefmt="psql")


__all__ = [
    "cashflow_table",
    "forecast_table",
    "income_table",
    "positions_table",
    "rent_matrix_table",
    "rentability_table",
    "wealth_table",
]
