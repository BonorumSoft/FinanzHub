"""Tests für ``app.scheduler`` (BlockingScheduler mit gemockten Jobs)."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.scheduler import build_scheduler


class TestScheduler:
    def test_builds_with_three_jobs(self) -> None:
        daily = MagicMock()
        monthly = MagicMock()
        quarterly = MagicMock()
        scheduler = build_scheduler(daily=daily, monthly=monthly, quarterly=quarterly)
        jobs = scheduler.get_jobs()
        assert len(jobs) == 3
        ids = {j.id for j in jobs}
        assert ids == {"daily_cycle", "monthly_cycle", "quarterly_cycle"}

    def test_jobs_have_descriptions(self) -> None:
        scheduler = build_scheduler(
            daily=MagicMock(), monthly=MagicMock(), quarterly=MagicMock()
        )
        for job in scheduler.get_jobs():
            assert job.name  # jeder Job hat einen Namen
