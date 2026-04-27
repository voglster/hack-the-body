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
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Callable, Literal

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


RULES: list[Rule] = [
    Rule(
        id="vitamins_missing", kind="vitamin",
        pushable=True, push_at=time(12, 0),
        evaluate=rule_vitamins_missing,
    ),
]
