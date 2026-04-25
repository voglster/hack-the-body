"""Coach scheduler.

Fires `generate_insight(trigger='scheduled')` at configured local times and
sends a push notification to every saved subscription. The schedule is
defined by the COACH_SCHEDULE_LOCAL env var (see app.config). If the LLM
is down or push fails for individual subscriptions, the job logs and moves
on; the next firing tries again.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime, time, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pymongo.asynchronous.database import AsyncDatabase

from app.config import Settings
from app.routers.vitamins import count_vitamins_today
from app.services.coach import generate_insight
from app.services.coach_weekly import generate_weekly_review
from app.services.food_repo import FoodRepo
from app.services.push import send_push

logger = logging.getLogger(__name__)


async def _scheduled_run(settings: Settings, db: AsyncDatabase) -> None:
    food_totals = await _today_food_totals(db)
    try:
        insight = await generate_insight(
            settings, db, food_totals=food_totals, trigger="scheduled",
        )
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


async def _vitamin_reminder_run(settings: Settings, db: AsyncDatabase) -> None:
    """Push 'did you take your vitamins?' if today's count is still 0."""
    repo = FoodRepo(db)
    now = datetime.now(UTC)
    start = datetime.combine(now.date(), time.min, tzinfo=UTC)
    end = start + timedelta(days=1)
    try:
        count, _ = await count_vitamins_today(repo, start, end)
    except Exception:
        logger.exception("vitamin reminder: count failed")
        return
    if count > 0:
        return
    try:
        result = await send_push(
            db, settings,
            {"title": "Vitamins", "body": "Did you take your vitamins yet?", "url": "/"},
        )
        logger.info("vitamin reminder push: %s", result)
    except Exception:
        logger.exception("vitamin reminder: push failed")


async def _today_food_totals(db: AsyncDatabase) -> dict:
    repo = FoodRepo(db)
    now = datetime.now(UTC)
    start = datetime.combine(now.date(), time.min, tzinfo=UTC)
    _ = start + timedelta(days=1)
    entries = await repo.list_entries_for_day(start)
    totals = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    for e in entries:
        m = e.get("macros") or {}
        for k in totals:
            v = m.get(k)
            if v is not None:
                totals[k] += float(v)
    return {k: round(v, 1) for k, v in totals.items()} | {"entries": len(entries)}


def build_scheduler(
    settings: Settings,
    db: AsyncDatabase,
    *,
    timezone: str | None = None,
) -> AsyncIOScheduler:
    """Build (but don't start) the coach scheduler.

    `timezone` defaults to the TZ env var via the OS (APScheduler reads
    `time.tzname`), so 'America/Denver' / Chicago whatever the container has.
    """
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
    vit = settings.vitamin_reminder_time
    if vit is not None:
        vhh, vmm = vit
        sched.add_job(
            _vitamin_reminder_run,
            CronTrigger(hour=vhh, minute=vmm, timezone=timezone),
            args=[settings, db],
            id=f"vitamin-reminder-{vhh:02d}-{vmm:02d}",
            replace_existing=True,
        )
    return sched
