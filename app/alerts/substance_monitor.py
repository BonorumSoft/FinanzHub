"""Substanz-Monitor.

Zwei Implementierungsvarianten:

- **Event-basiert**: Liquides Vermögen sinkt > X% in N Tagen (Rolling).
- **Monatlich**: N Monate in Folge sinkend (aus ``networth_history``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.engine import Engine

from app.config_loader import AppSettings
from app.data.db import execute
from app.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SubstanceEvent:
    trigger: str  # "drop" | "consecutive_decline"
    threshold: float
    period_days: int
    current_value: float
    reference_value: float
    delta_percent: float
    details: str

    def to_dict(self) -> dict:
        return {
            "trigger": self.trigger,
            "threshold": self.threshold,
            "period_days": self.period_days,
            "current_value": round(self.current_value, 2),
            "reference_value": round(self.reference_value, 2),
            "delta_percent": round(self.delta_percent, 2),
            "details": self.details,
        }


def detect_event_based(
    engine: Engine, settings: AppSettings
) -> list[SubstanceEvent]:
    """Liquides Vermögen (Bank + Securities) ist > X% unter seinem Stand
    vor ``schwellwert_substanz_tage`` Tagen.
    """
    threshold_pct = settings.vermoegen.schwellwert_substanz_prozent
    days = settings.vermoegen.schwellwert_substanz_tage
    cutoff = date.today() - timedelta(days=days)

    # Aktueller Stand: letzte Nettovermögens-Zeile
    latest = execute(
        engine,
        "SELECT snapshot_date, bank_total, securities_total "
        "FROM networth_history ORDER BY snapshot_date DESC LIMIT 1",
    )
    if not latest:
        return []
    current = float(latest[0]["bank_total"]) + float(latest[0]["securities_total"])

    # Referenz: Zeile, die möglichst nahe an ``cutoff`` liegt
    reference_rows = execute(
        engine,
        "SELECT bank_total, securities_total, snapshot_date "
        "FROM networth_history WHERE snapshot_date <= :d "
        "ORDER BY snapshot_date DESC LIMIT 1",
        {"d": cutoff.isoformat()},
    )
    if not reference_rows:
        return []
    reference = float(reference_rows[0]["bank_total"]) + float(reference_rows[0]["securities_total"])
    if reference <= 0:
        return []

    delta_pct = (current - reference) / reference * 100.0
    if delta_pct < -abs(threshold_pct):
        return [
            SubstanceEvent(
                trigger="drop",
                threshold=threshold_pct,
                period_days=days,
                current_value=current,
                reference_value=reference,
                delta_percent=delta_pct,
                details=(
                    f"Liquides Vermögen in {days} Tagen um "
                    f"{abs(delta_pct):.2f}% gefallen (>{threshold_pct}%)"
                ),
            )
        ]
    return []


def detect_consecutive_decline(
    engine: Engine, settings: AppSettings
) -> list[SubstanceEvent]:
    """N Monate in Folge sinkendes Nettovermögen (Substanzverzehr)."""
    months = settings.vermoegen.substance_consecutive_months
    rows = execute(
        engine,
        "SELECT snapshot_date, net_worth FROM networth_history "
        "ORDER BY snapshot_date ASC",
    )
    if len(rows) < months + 1:
        return []

    # Wir vergleichen Monatsend-Werte. Vereinfachung: gruppiere nach Jahr-Monat
    # und nimm den letzten Wert jedes Monats.
    monthly: dict[tuple[int, int], float] = {}
    for r in rows:
        d = r["snapshot_date"]
        if isinstance(d, str):
            from datetime import datetime

            d = datetime.fromisoformat(d).date()
        key = (d.year, d.month)
        monthly[key] = float(r["net_worth"])

    sorted_keys = sorted(monthly.keys())
    streak = 1
    for prev_key, curr_key in zip(sorted_keys, sorted_keys[1:], strict=False):
        if monthly[curr_key] < monthly[prev_key]:
            streak += 1
        else:
            streak = 1
        if streak >= months:
            return [
                SubstanceEvent(
                    trigger="consecutive_decline",
                    threshold=settings.vermoegen.substanz_consecutive_months
                    if hasattr(settings.vermoegen, "substanz_consecutive_months")
                    else months,
                    period_days=0,
                    current_value=monthly[curr_key],
                    reference_value=monthly[prev_key],
                    delta_percent=(
                        (monthly[curr_key] - monthly[prev_key]) / monthly[prev_key] * 100.0
                        if monthly[prev_key] > 0
                        else 0.0
                    ),
                    details=(
                        f"Nettovermögen {months} Monate in Folge gesunken "
                        f"(aktuell: {monthly[curr_key]:.2f} €)"
                    ),
                )
            ]
    return []


def detect_all(engine: Engine, settings: AppSettings) -> list[SubstanceEvent]:
    events: list[SubstanceEvent] = []
    events.extend(detect_event_based(engine, settings))
    events.extend(detect_consecutive_decline(engine, settings))
    return events


__all__ = [
    "SubstanceEvent",
    "detect_all",
    "detect_consecutive_decline",
    "detect_event_based",
]
