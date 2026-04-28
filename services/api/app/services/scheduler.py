"""Coach + nudges scheduler.

Two unrelated jobs share this scheduler:

* Coach insights — fires `generate_insight(trigger='scheduled')` at
  COACH_SCHEDULE_LOCAL times and sends a push.
* Weekly review — Sunday at COACH_WEEKLY_LOCAL.
* Prescriptive nudges push — fires `nudges_push_tick` at 10:00, 12:00,
  21:30 local (the buckets baked into `services/nudges.py`). The old
  standalone vitamin reminder is subsumed by the 12:00 nudges tick.

Failure isolation: each job catches its own exceptions; one failing job
doesn't stop the others. The scheduler itself uses APScheduler's default
local-tz handling, driven by the TZ env var.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pymongo.asynchronous.database import AsyncDatabase

from app.config import Settings
from app.services.coach import generate_insight
from app.services.coach_weekly import generate_weekly_review
from app.services.nudges import PUSH_BUCKETS, nudges_push_tick
from app.services.push import send_push

logger = logging.getLogger(__name__)


async def _scheduled_run(settings: Settings, db: AsyncDatabase) -> None:
    try:
        # generate_insight resolves the local-day window from $TZ and
        # computes food_totals itself, so the scheduler doesn't need to
        # (and used to get it wrong by anchoring on UTC midnight).
        insight = await generate_insight(settings, db, trigger="scheduled")
    except Exception:
        logger.exception("scheduled coach: generate_insight failed")
        return
    try:
        result = await send_push(
            db, settings,
            {"title": "Coach", "body": insight.text, "url": "/"},
        )
        logger.info("scheduled coach push: %s", result)
    except Exception:
        logger.exception("scheduled coach: push failed")


async def _weekly_run(settings: Settings, db: AsyncDatabase) -> None:
    try:
        insight = await generate_weekly_review(settings, db, trigger="weekly")
    except Exception:
        logger.exception("weekly coach: generate_weekly_review failed")
        return
    try:
        result = await send_push(
            db, settings,
            {"title": "Weekly review", "body": insight.text[:200], "url": "/"},
        )
        logger.info("weekly coach push: %s", result)
    except Exception:
        logger.exception("weekly coach: push failed")


async def _nudges_push_run(settings: Settings, db: AsyncDatabase) -> None:
    try:
        await nudges_push_tick(datetime.now(UTC), settings, db)
    except Exception:
        logger.exception("nudges push tick: failed")


def build_scheduler(
    settings: Settings,
    db: AsyncDatabase,
    *,
    timezone: str | None = None,
) -> AsyncIOScheduler:
    """Build (but don't start) the scheduler."""
    sched = AsyncIOScheduler(timezone=timezone)
    for hh, mm in settings.coach_schedule_times:
        sched.add_job(
            _scheduled_run,
            CronTrigger(hour=hh, minute=mm, timezone=timezone),
            args=[settings, db],
            id=f"coach-{hh:02d}-{mm:02d}",
            replace_existing=True,
        )
    whh, wmm = settings.coach_weekly_time
    sched.add_job(
        _weekly_run,
        CronTrigger(day_of_week="sun", hour=whh, minute=wmm, timezone=timezone),
        args=[settings, db],
        id=f"coach-weekly-{whh:02d}-{wmm:02d}",
        replace_existing=True,
    )
    for hh, mm in PUSH_BUCKETS:
        sched.add_job(
            _nudges_push_run,
            CronTrigger(hour=hh, minute=mm, timezone=timezone),
            args=[settings, db],
            id=f"nudges-push-{hh:02d}-{mm:02d}",
            replace_existing=True,
        )
    return sched
