"""Tests für ``app.alerts.substance_monitor``."""

from __future__ import annotations

from datetime import date, timedelta

from freezegun import freeze_time
from sqlalchemy import text

from app.alerts.substance_monitor import detect_all, detect_consecutive_decline, detect_event_based
from app.config_loader import AppSettings


def _insert_snapshot(engine, day: date, bank: float, securities: float) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO networth_history (snapshot_date, bank_total, securities_total, "
                "real_estate_equity, net_worth) VALUES (:d, :b, :s, 0, :n)"
            ),
            {"d": day.isoformat(), "b": f"{bank:.2f}", "s": f"{securities:.2f}", "n": f"{bank + securities:.2f}"},
        )


@freeze_time("2026-06-15")
class TestSubstanceMonitor:
    def test_substance_draw_detected_above_threshold(self, db) -> None:
        today = date(2026, 6, 15)
        _insert_snapshot(db, today - timedelta(days=30), 10_000, 0)
        _insert_snapshot(db, today, 9_000, 0)  # -10 %
        settings = AppSettings()
        settings.vermoegen.schwellwert_substanz_prozent = 5.0
        events = detect_event_based(db, settings)
        assert len(events) == 1
        assert events[0].trigger == "drop"

    def test_substance_draw_not_triggered_below_threshold(self, db) -> None:
        today = date(2026, 6, 15)
        _insert_snapshot(db, today - timedelta(days=30), 10_000, 0)
        _insert_snapshot(db, today, 9_800, 0)  # -2 %
        settings = AppSettings()
        events = detect_event_based(db, settings)
        assert events == []

    def test_consecutive_decline(self, db) -> None:
        # 4 Monate in Folge sinkend → Monat 4 löst aus
        for offset, value in [(0, 10_000), (1, 9_900), (2, 9_800), (3, 9_700)]:
            day = date(2026, 3 + offset, 28)
            _insert_snapshot(db, day, value, 0)
        settings = AppSettings()
        settings.vermoegen.substance_consecutive_months = 3
        events = detect_consecutive_decline(db, settings)
        assert len(events) == 1
        assert events[0].trigger == "consecutive_decline"

    def test_detect_all_aggregates(self, db) -> None:
        today = date(2026, 6, 15)
        _insert_snapshot(db, today - timedelta(days=30), 10_000, 0)
        _insert_snapshot(db, today, 8_000, 0)
        settings = AppSettings()
        events = detect_all(db, settings)
        assert any(e.trigger == "drop" for e in events)
