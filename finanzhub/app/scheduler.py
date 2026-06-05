"""APScheduler-basierter Scheduler für FinanzHub.

Drei Cron-Jobs:

- täglich 06:00 UTC → :func:`run_daily_cycle`
- monatlich 1., 09:00 UTC → :func:`run_monthly_cycle`
- quartalsweise 1.1./1.4./1.7./1.10., 07:00 UTC → :func:`run_quarterly_cycle`

Die Cycles sind Platzhalter — die konkreten Aufrufe (Pull/Events/Notify)
werden beim Scheduler-Start in :mod:`app.main` registriert.
"""

from __future__ import annotations

from collections.abc import Callable

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from app.logger import get_logger

logger = get_logger(__name__)


def build_scheduler(
    daily: Callable[[], None],
    monthly: Callable[[], None],
    quarterly: Callable[[], None],
) -> BlockingScheduler:
    """Erzeugt einen BlockingScheduler mit den drei Standard-Cron-Jobs."""
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        daily,
        CronTrigger(hour=6, minute=0),
        id="daily_cycle",
        name="Täglicher Report-Zyklus",
        replace_existing=True,
    )
    scheduler.add_job(
        monthly,
        CronTrigger(day=1, hour=9, minute=0),
        id="monthly_cycle",
        name="Monatlicher Report-Zyklus",
        replace_existing=True,
    )
    scheduler.add_job(
        quarterly,
        CronTrigger(month="1,4,7,10", day=1, hour=7, minute=0),
        id="quarterly_cycle",
        name="Quartalsweiser Report-Zyklus",
        replace_existing=True,
    )
    logger.info("Scheduler mit 3 Cron-Jobs konfiguriert")
    return scheduler


__all__ = ["build_scheduler"]
