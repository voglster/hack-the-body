"""Prescriptive nudges — rules engine.

A `Rule` is a pure function over a `NudgeContext` snapshot. `evaluate_all`
runs every rule, filters out dismissed ones, and returns a deterministic
list of `FiredNudge` instances in registry order.

Thresholds, the waking-day window, and the rule registry all live in this
file so tuning is a one-file change. See
`docs/superpowers/specs/2026-04-27-prescriptive-nudges-design.md`.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pymongo.asynchronous.database import AsyncDatabase

from app.config import Settings
from app.services.nudge_dismissals import get_active_dismissals
from app.services.push import send_push

logger = logging.getLogger(__name__)

# ----- day-window constants (waking hours used for pace math) -----
DAY_START_HOUR = 6   # 6:00 local
DAY_END_HOUR = 22    # 22:00 local

# ----- per-rule floor thresholds (don't fire before this hour, local TZ) -----
VITAMINS_FLOOR = time(12, 0)
WATER_FLOOR = time(10, 0)
WEIGHIN_FLOOR = time(10, 0)
STEPS_FLOOR = time(12, 0)

# ----- pace tolerances (lower = more aggressive nudging) -----
WATER_PACE_TOLERANCE = 0.7   # fire when intake < target * elapsed * 0.7
STEPS_PACE_TOLERANCE = 0.6   # fire when steps  < target * elapsed * 0.6

# ----- bedtime window (local TZ) -----
BEDTIME_START = time(21, 30)
BEDTIME_END = time(22, 30)

# ----- push buckets (hour, minute) — must align with rules' push_at -----
PUSH_BUCKETS: list[tuple[int, int]] = [(10, 0), (12, 0), (21, 30)]


Severity = Literal["info", "warn"]


@dataclass(frozen=True)
class FiredNudge:
    id: str
    kind: str
    severity: Severity
    title: str
    body: str
    dismissable: bool = True


@dataclass(frozen=True)
class NudgeContext:
    """Snapshot of everything any rule might need.

    Built once per evaluation by `build_context`.
    """
    now_local: datetime
    targets: dict[str, Any]
    vitamins_count_today: int
    water_oz_today: float
    weight_logged_today: bool
    steps_today: int | None         # None = no daily summary doc yet


@dataclass
class Rule:
    id: str
    kind: str
    pushable: bool
    push_at: time | None
    evaluate: Callable[[NudgeContext], FiredNudge | None]


# ----- helpers -----

def _elapsed_fraction(now_local: datetime) -> float:
    """Fraction of the waking-day window that has passed at `now_local`.

    Returns 0.0 before DAY_START_HOUR, 1.0 after DAY_END_HOUR. Independent
    of seconds; granularity is minutes.
    """
    minutes_in = (now_local.hour - DAY_START_HOUR) * 60 + now_local.minute
    minutes_total = (DAY_END_HOUR - DAY_START_HOUR) * 60
    if minutes_in <= 0:
        return 0.0
    if minutes_in >= minutes_total:
        return 1.0
    return minutes_in / minutes_total


# ----- rules -----

def rule_vitamins_missing(ctx: NudgeContext) -> FiredNudge | None:
    if ctx.now_local.time() < VITAMINS_FLOOR:
        return None
    if ctx.vitamins_count_today > 0:
        return None
    return FiredNudge(
        id="vitamins_missing",
        kind="vitamin",
        severity="warn",
        title="Vitamins not taken yet",
        body="It's past noon and you haven't logged your stack.",
    )


def rule_water_below_pace(ctx: NudgeContext) -> FiredNudge | None:
    if ctx.now_local.time() < WATER_FLOOR:
        return None
    target = ctx.targets.get("daily_water_oz")
    if not target:  # None or 0 → silent (rule doesn't apply)
        return None
    elapsed = _elapsed_fraction(ctx.now_local)
    threshold = target * elapsed * WATER_PACE_TOLERANCE
    if ctx.water_oz_today >= threshold:
        return None
    return FiredNudge(
        id="water_below_pace",
        kind="water",
        severity="info",
        title="Drink some water",
        body=f"{int(ctx.water_oz_today)} of {int(target)} oz so far — behind pace.",
    )


def rule_no_weighin(ctx: NudgeContext) -> FiredNudge | None:
    if ctx.now_local.time() < WEIGHIN_FLOOR:
        return None
    if ctx.weight_logged_today:
        return None
    return FiredNudge(
        id="no_weighin",
        kind="weight",
        severity="info",
        title="No weigh-in yet",
        body="Step on the scale when you get a moment.",
    )


def rule_steps_below_pace(ctx: NudgeContext) -> FiredNudge | None:
    if ctx.now_local.time() < STEPS_FLOOR:
        return None
    if ctx.steps_today is None:
        return None  # no Garmin data yet — can't judge
    target = ctx.targets.get("step_goal_override")
    if not target:
        return None
    elapsed = _elapsed_fraction(ctx.now_local)
    threshold = target * elapsed * STEPS_PACE_TOLERANCE
    if ctx.steps_today >= threshold:
        return None
    return FiredNudge(
        id="steps_below_pace",
        kind="steps",
        severity="info",
        title="Behind on steps",
        body=f"{ctx.steps_today:,} of {target:,} so far — go for a walk.",
    )


def rule_bedtime_reminder(ctx: NudgeContext) -> FiredNudge | None:
    t = ctx.now_local.time()
    if t < BEDTIME_START or t >= BEDTIME_END:
        return None
    return FiredNudge(
        id="bedtime_reminder",
        kind="bedtime",
        severity="info",
        title="Wind down",
        body="In bed by 10pm — close out and head up.",
    )


RULES: list[Rule] = [
    Rule(
        id="vitamins_missing", kind="vitamin",
        pushable=True, push_at=time(12, 0),
        evaluate=rule_vitamins_missing,
    ),
    Rule(
        id="water_below_pace", kind="water",
        pushable=False, push_at=None,
        evaluate=rule_water_below_pace,
    ),
    Rule(
        id="no_weighin", kind="weight",
        pushable=True, push_at=time(10, 0),
        evaluate=rule_no_weighin,
    ),
    Rule(
        id="steps_below_pace", kind="steps",
        pushable=False, push_at=None,
        evaluate=rule_steps_below_pace,
    ),
    Rule(
        id="bedtime_reminder", kind="bedtime",
        pushable=True, push_at=time(21, 30),
        evaluate=rule_bedtime_reminder,
    ),
]


def evaluate_all(
    ctx: NudgeContext,
    *,
    dismissed_ids: set[str],
) -> list[FiredNudge]:
    """Run every rule. Skip dismissed. Swallow per-rule exceptions.

    Returns nudges in `RULES` registry order — render order is tunable
    by reordering `RULES`.
    """
    out: list[FiredNudge] = []
    for rule in RULES:
        if rule.id in dismissed_ids:
            continue
        try:
            nudge = rule.evaluate(ctx)
        except Exception:
            logger.exception("nudges: rule %s raised — skipping", rule.id)
            continue
        if nudge is not None:
            out.append(nudge)
    return out


# ----- context assembly -----

def _local_tz() -> ZoneInfo:
    name = os.environ.get("TZ") or "UTC"
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo("UTC")


def _local_day_window_utc(now_utc: datetime) -> tuple[datetime, datetime, datetime]:
    """Return (start_utc, end_utc, now_local) for the user's local 'today'."""
    tz = _local_tz()
    now_local = now_utc.astimezone(tz)
    start_local = datetime.combine(now_local.date(), time.min, tzinfo=tz)
    start_utc = start_local.astimezone(UTC)
    end_utc = start_utc + timedelta(days=1)
    return start_utc, end_utc, now_local


async def build_context(
    db: AsyncDatabase,
    *,
    now_utc: datetime | None = None,
) -> NudgeContext:
    """Snapshot every signal a rule might need.

    Reads targets + today's vitamin count + today's water oz + today's
    weight presence + today's steps. Empty/missing data → safe defaults
    (zeroes / False / None).
    """
    if now_utc is None:
        now_utc = datetime.now(UTC)
    start_utc, end_utc, now_local = _local_day_window_utc(now_utc)

    targets_doc = await db["user_profile"].find_one({"_id": "targets"}) or {}
    targets = {k: v for k, v in targets_doc.items() if k != "_id"}

    # Vitamins + water both come from the meal entries collection.
    cur = db["meal_entries"].find({"ts": {"$gte": start_utc, "$lt": end_utc}})
    vitamins_count = 0
    water_grams = 0.0
    async for e in cur:
        name = e.get("food_name")
        if name == "Vitamins":
            vitamins_count += 1
        elif name == "Water":
            water_grams += float(e.get("quantity_g") or 0)
    water_oz = water_grams / 29.5735 if water_grams else 0.0

    weight_doc = await db["metrics_weight"].find_one(
        {"ts": {"$gte": start_utc, "$lt": end_utc}},
    )
    weight_logged = weight_doc is not None

    # Steps: today's daily_summary doc, if any.
    summary = await db["metrics_daily_summary"].find_one(
        {"ts": {"$gte": start_utc, "$lt": end_utc}, "step_goal": {"$ne": None}},
        sort=[("ts", -1)],
    )
    steps_today: int | None = None
    if summary is not None and summary.get("steps") is not None:
        steps_today = int(summary["steps"])

    return NudgeContext(
        now_local=now_local,
        targets=targets,
        vitamins_count_today=vitamins_count,
        water_oz_today=water_oz,
        weight_logged_today=weight_logged,
        steps_today=steps_today,
    )


PUSH_GRACE_MINUTES = 5


def _matching_bucket(now_local: datetime) -> tuple[int, int] | None:
    """Return the push bucket that `now_local` matches within grace, or None.

    Buckets are wall-clock times; a tick at 12:04 still matches the 12:00
    bucket. Anything farther than PUSH_GRACE_MINUTES away matches nothing.
    """
    for hh, mm in PUSH_BUCKETS:
        bucket_minutes = hh * 60 + mm
        now_minutes = now_local.hour * 60 + now_local.minute
        if abs(now_minutes - bucket_minutes) <= PUSH_GRACE_MINUTES:
            return (hh, mm)
    return None


async def nudges_push_tick(
    now_utc: datetime,
    settings: Settings,
    db: AsyncDatabase,
) -> None:
    """Evaluate push-eligible rules for the current bucket and send pushes.

    Pure with respect to wall clock — pass `now_utc` explicitly so tests
    can drive the function deterministically. The scheduler binding in
    `services/scheduler.py` calls this with `datetime.now(UTC)`.
    """
    ctx = await build_context(db, now_utc=now_utc)
    bucket = _matching_bucket(ctx.now_local)
    if bucket is None:
        return
    bucket_time = time(*bucket)
    dismissed = await get_active_dismissals(db, now_utc=now_utc)
    for rule in RULES:
        if not rule.pushable or rule.push_at != bucket_time:
            continue
        if rule.id in dismissed:
            continue
        try:
            fired = rule.evaluate(ctx)
        except Exception:
            logger.exception("nudges push: rule %s raised", rule.id)
            continue
        if fired is None:
            continue
        try:
            await send_push(
                db, settings,
                {"title": fired.title, "body": fired.body, "url": "/"},
            )
        except Exception:
            logger.exception("nudges push: send failed for %s", fired.id)
