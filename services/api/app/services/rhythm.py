"""Daily rhythm: the few fixed moments that make logging a habit.

- Weigh-in brief: the first weight of the day triggers the coach's brief.
- Mid-window checks: a push only if nothing's been logged since the last check.
- Window close: "anything you didn't log?"
- Lapses: after two blank days every ask shrinks to "just log one thing".

Success is measured as days logged per week, not a streak — a missed day
shouldn't cost anything to come back from. Each moment fires at most once
per local day (`rhythm_log`).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from app.config import Settings
from app.services.capture import CAPTURES, local_day_start, local_tz
from app.services.eating_window import window_bounds
from app.services.push import send_push

log = logging.getLogger(__name__)

RHYTHM_LOG = "rhythm_log"
LAPSE_DAYS = 2
BRIEF_UNTIL_HOUR = 13
MID_CHECK_OFFSETS = (timedelta(hours=2, minutes=30), timedelta(hours=6, minutes=30))
CLOSE_GRACE = timedelta(hours=1)
TRACKED_WEEK_DAYS = 4
UNTRACKED_WEEK_DAYS = 1
LB_PER_KG = 2.2046226


async def logged_dates(db: AsyncDatabase, since: datetime) -> set[date]:
    tz = local_tz()
    out: set[date] = set()
    async for e in db["meal_entries"].find({"ts": {"$gte": since}, "food_category": "food"}):
        ts = e["ts"] if e["ts"].tzinfo else e["ts"].replace(tzinfo=UTC)
        out.add(ts.astimezone(tz).date())
    return out


def is_lapsed(dates: set[date], today: date) -> bool:
    """Nothing logged today or on the LAPSE_DAYS days before it."""
    return all(today - timedelta(days=d) not in dates for d in range(LAPSE_DAYS + 1))


def weekly_weight_by_tracking(
    dates: set[date],
    weights: list[tuple[date, float]],
) -> dict[str, Any]:
    """Average weekly weight change (lb) in well-logged weeks vs barely-logged ones."""
    weeks: dict[date, list[tuple[date, float]]] = {}
    for d, kg in sorted(weights):
        weeks.setdefault(d - timedelta(days=d.weekday()), []).append((d, kg))
    tracked: list[float] = []
    untracked: list[float] = []
    for monday, pts in weeks.items():
        if len(pts) < 2:  # noqa: PLR2004 — a change needs two weigh-ins
            continue
        change_lb = (pts[-1][1] - pts[0][1]) * LB_PER_KG
        logged = sum(monday + timedelta(days=i) in dates for i in range(7))
        if logged >= TRACKED_WEEK_DAYS:
            tracked.append(change_lb)
        elif logged <= UNTRACKED_WEEK_DAYS:
            untracked.append(change_lb)

    def avg(xs: list[float]) -> float | None:
        return round(sum(xs) / len(xs), 1) if xs else None

    return {
        "tracked_lb_per_week": avg(tracked),
        "tracked_weeks": len(tracked),
        "untracked_lb_per_week": avg(untracked),
        "untracked_weeks": len(untracked),
    }


async def status(db: AsyncDatabase) -> dict[str, Any]:
    tz = local_tz()
    now_local = datetime.now(tz)
    today = now_local.date()
    since = local_day_start(datetime.now(UTC)) - timedelta(days=182)
    dates = await logged_dates(db, since)
    weights = []
    async for w in db["metrics_weight"].find({"ts": {"$gte": since}}):
        ts = w["ts"] if w["ts"].tzinfo else w["ts"].replace(tzinfo=UTC)
        if w.get("kg") is not None:
            weights.append((ts.astimezone(tz).date(), float(w["kg"])))
    pending = await db[CAPTURES].count_documents(
        {"status": {"$in": ["pending", "needs_confirm", "placeholder"]}, "ts": {"$gte": since}},
    )
    return {
        "logged_today": today in dates,
        "days_logged_7d": sum(today - timedelta(days=i) in dates for i in range(7)),
        "lapsed": is_lapsed(dates, today),
        "pending": pending,
        "weight_by_tracking": weekly_weight_by_tracking(dates, weights),
    }


# ---------- the scheduled moments ----------


async def _once(db: AsyncDatabase, day: date, kind: str) -> bool:
    """Claim today's `kind` moment; False if it already fired."""
    res = await db[RHYTHM_LOG].update_one(
        {"date": day.isoformat(), "kind": kind},
        {"$setOnInsert": {"at": datetime.now(UTC)}},
        upsert=True,
    )
    return res.upserted_id is not None


async def _food_since(db: AsyncDatabase, since: datetime) -> bool:
    return (
        await db["meal_entries"].find_one(
            {"ts": {"$gte": since.astimezone(UTC)}, "food_category": "food"},
        )
        is not None
    )


def _push(title: str, body: str) -> dict[str, Any]:
    return {"title": title, "body": body, "url": "/log"}


def _at(day: date, hhmm: str, tz: Any) -> datetime:
    hour, minute = (int(x) for x in hhmm.split(":"))
    return datetime.combine(day, time(hour, minute), tzinfo=tz)


async def due_pushes(db: AsyncDatabase, now_local: datetime) -> list[dict[str, Any]]:
    """Which rhythm pushes are due right now (claims them)."""
    today = now_local.date()
    targets = await db["user_profile"].find_one({"_id": "targets"}) or {}
    start, end = window_bounds(targets)
    opens, closes = _at(today, start, now_local.tzinfo), _at(today, end, now_local.tzinfo)
    dates = await logged_dates(db, local_day_start(datetime.now(UTC)) - timedelta(days=LAPSE_DAYS))
    lapsed = is_lapsed(dates, today)
    out: list[dict[str, Any]] = []

    if opens <= now_local < closes:
        checkpoints = [opens + off for off in MID_CHECK_OFFSETS]
        for i, cp in enumerate(checkpoints):
            since = opens if i == 0 else checkpoints[i - 1]
            if (
                now_local >= cp
                and not await _food_since(db, since)
                and await _once(db, today, f"mid{i}")
            ):
                body = (
                    "Just log one thing today. Anything counts."
                    if lapsed
                    else f"Nothing logged since {since.strftime('%-I:%M%p').lower()}. Tap to log."
                )
                out.append(_push("Log it", body))

    if closes <= now_local < closes + CLOSE_GRACE and await _once(db, today, "close"):
        body = (
            "Anything you ate that isn't logged?"
            if today in dates
            else "Nothing logged today. Log one thing before bed?"
        )
        out.append(_push("Window's closed", body))
    return out


async def weigh_in_due(db: AsyncDatabase, now_local: datetime) -> bool:
    if now_local.hour >= BRIEF_UNTIL_HOUR:
        return False
    weight = await db["metrics_weight"].find_one(
        {"ts": {"$gte": local_day_start(datetime.now(UTC))}},
    )
    return weight is not None and await _once(db, now_local.date(), "weigh_in")


async def rhythm_tick(settings: Settings, db: AsyncDatabase) -> None:
    now_local = datetime.now(local_tz())
    if await weigh_in_due(db, now_local):
        from app.services.coach import generate_insight  # noqa: PLC0415 — coach imports capture

        insight = await generate_insight(settings, db, trigger="weigh_in")
        await send_push(db, settings, _push("Morning brief", insight.text[:200]))
        log.info("rhythm: weigh-in brief sent")
    for payload in await due_pushes(db, now_local):
        await send_push(db, settings, payload)
        log.info("rhythm: %s — %s", payload["title"], payload["body"])
