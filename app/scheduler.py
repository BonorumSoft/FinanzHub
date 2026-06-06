"""APScheduler-basierter Scheduler für FinanzHub.

Drei Cron-Jobs:

- täglich 06:00 UTC → :func:`run_daily_cycle`
- monatlich 1., 09:00 UTC → :func:`run_monthly_cycle`
- quartalsweise 1.1./1.4./1.7./1.10., 07:00 UTC → :func:`run_quarterly_cycle`

Optional:

- Inbox-Polling: Interval-Job mit ``poll_interval_seconds`` aus
  ``inbox.yaml``. Wird automatisch registriert, wenn ``inbox_poll``
  als Callable übergeben wird.

Die Cycles sind Platzhalter — die konkreten Aufrufe (Pull/Events/Notify)
werden beim Scheduler-Start in :mod:`app.main` registriert.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.logger import get_logger

logger = get_logger(__name__)


def build_scheduler(
    daily: Callable[[], None],
    monthly: Callable[[], None],
    quarterly: Callable[[], None],
    inbox_poll: Callable[[], Any] | None = None,
    inbox_poll_seconds: int = 60,
) -> BlockingScheduler:
    """Erzeugt einen BlockingScheduler mit den drei Standard-Cron-Jobs.

    Args:
        daily: Tageszyklus-Callable.
        monthly: Monatszyklus-Callable.
        quarterly: Quartalszyklus-Callable.
        inbox_poll: Optionaler Callable für Beleg-Inbox (z. B. ``InboxEngine.process_inbox``).
        inbox_poll_seconds: Polling-Intervall in Sekunden (default 60).
    """
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

    if inbox_poll is not None:
        scheduler.add_job(
            inbox_poll,
            IntervalTrigger(seconds=max(10, int(inbox_poll_seconds))),
            id="inbox_poll",
            name="Beleg-Inbox Polling",
            replace_existing=True,
            max_instances=1,  # kein paralleler Lauf
            coalesce=True,
        )
        logger.info(
            "Inbox-Poll registriert (alle %d Sekunden)", inbox_poll_seconds
        )

    logger.info("Scheduler konfiguriert (daily + monthly + quarterly%s)",
                " + inbox" if inbox_poll else "")
    return scheduler


__all__ = ["build_scheduler"]
