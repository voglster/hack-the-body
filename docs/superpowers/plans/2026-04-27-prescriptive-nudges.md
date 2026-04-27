# Prescriptive Nudges Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a top-of-dashboard "Today" nudges card driven by a stateless rules engine (vitamins, water, weigh-in, steps, bedtime) plus three time-anchored web pushes (10:00, 12:00, 21:30 local).

**Architecture:** Pure Python rules engine in `services/nudges.py`. Each rule is a dataclass with an `evaluate(ctx)` callable. `GET /nudges` recomputes on every request from a context-doc snapshot. Per-day dismissal overlay in a new `nudge_dismissals` Mongo collection. Push fires from the existing APScheduler in `services/scheduler.py` — the existing standalone vitamin reminder job is replaced by the unified nudges push tick.

**Tech Stack:** FastAPI, Pydantic, Motor (async MongoDB via `mongomock_motor` for tests), APScheduler, pywebpush. React 19 + Vite + @tanstack/react-query for the FE.

**Spec:** `docs/superpowers/specs/2026-04-27-prescriptive-nudges-design.md`

---

## File Structure

**Backend (new):**
- `services/api/app/services/nudges.py` — rules engine, types, constants, `evaluate_all`, `build_context`
- `services/api/app/services/nudge_dismissals.py` — read/write helpers for the `nudge_dismissals` collection
- `services/api/app/routers/nudges.py` — `GET /nudges`, `POST /nudges/dismiss`
- `services/api/tests/test_nudges_engine.py` — rule-by-rule unit tests + `evaluate_all` tests
- `services/api/tests/test_nudges_router.py` — endpoint tests
- `services/api/tests/test_nudges_scheduler.py` — push tick tests

**Backend (modified):**
- `services/api/app/main.py` — include the new router
- `services/api/app/services/scheduler.py` — replace `_vitamin_reminder_run` with `_nudges_push_run`, schedule three cron jobs
- `services/api/app/db.py` — add `nudge_dismissals` collection ensure (if needed)
- `services/api/app/config.py` — drop `vitamin_reminder_local` (no longer used) — actually KEEP and ignore for backward compat; mark deprecated in a comment

**Frontend (new):**
- `services/web/src/api/nudges.ts` — `fetchNudges`, `dismissNudge`
- `services/web/src/components/NudgesCard.tsx`
- `services/web/src/components/NudgesCard.test.tsx`

**Frontend (modified):**
- `services/web/src/api/types.ts` — `FiredNudge`, `NudgesResponse`, dismiss request shape
- `services/web/src/api/client.ts` — re-export `nudgesFetch` / `nudgesDismiss` on the `api` object
- `services/web/src/pages/Dashboard.tsx` — mount `<NudgesCard />` above existing cards

---

## Task 1: Skeleton — types, constants, empty registry

Build the module shell so later tasks have a place to put rules. No rule logic yet; just the types and the day-window math. TDD the constants and `_elapsed_fraction`.

**Files:**
- Create: `services/api/app/services/nudges.py`
- Create: `services/api/tests/test_nudges_engine.py`

- [ ] **Step 1: Write failing tests for the day-window helper**

Create `services/api/tests/test_nudges_engine.py`:

```python
"""Unit tests for the nudges rules engine."""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from app.services.nudges import (
    DAY_END_HOUR,
    DAY_START_HOUR,
    FiredNudge,
    Rule,
    _elapsed_fraction,
)


MT = ZoneInfo("America/Denver")


class TestDayWindow:
    def test_constants(self):
        assert DAY_START_HOUR == 6
        assert DAY_END_HOUR == 22

    def test_elapsed_before_window(self):
        # 5am — before window starts → 0.0
        now = datetime(2026, 4, 27, 5, 0, tzinfo=MT)
        assert _elapsed_fraction(now) == 0.0

    def test_elapsed_at_start(self):
        now = datetime(2026, 4, 27, 6, 0, tzinfo=MT)
        assert _elapsed_fraction(now) == 0.0

    def test_elapsed_midday(self):
        # 1pm — 7h into a 16h window → 7/16 = 0.4375
        now = datetime(2026, 4, 27, 13, 0, tzinfo=MT)
        assert _elapsed_fraction(now) == pytest.approx(7 / 16)

    def test_elapsed_at_end(self):
        now = datetime(2026, 4, 27, 22, 0, tzinfo=MT)
        assert _elapsed_fraction(now) == 1.0

    def test_elapsed_after_window(self):
        now = datetime(2026, 4, 27, 23, 30, tzinfo=MT)
        assert _elapsed_fraction(now) == 1.0


class TestTypes:
    def test_fired_nudge_shape(self):
        n = FiredNudge(
            id="x", kind="water", severity="info",
            title="t", body="b", dismissable=True,
        )
        assert n.id == "x"
        assert n.severity in {"info", "warn"}

    def test_rule_shape(self):
        r = Rule(
            id="x", kind="water", pushable=False, push_at=None,
            evaluate=lambda ctx: None,
        )
        assert r.pushable is False
```

- [ ] **Step 2: Run tests — expect import failure**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_engine.py -x`
Expected: FAIL — module `app.services.nudges` does not exist.

- [ ] **Step 3: Create the module**

Create `services/api/app/services/nudges.py`:

```python
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
PUSH_BUCKETS: list[tuple[int, int]] = [(10, 0), (12, 0), 21 and (21, 30)]
# fixed below — Python doesn't like the inline expression above
PUSH_BUCKETS = [(10, 0), (12, 0), (21, 30)]


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


# Rule registry placeholder — populated by later tasks.
RULES: list[Rule] = []
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_engine.py -x`
Expected: PASS — 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/nudges.py services/api/tests/test_nudges_engine.py
git commit -m "feat(nudges): module skeleton — types, constants, day-window helper"
```

---

## Task 2: Rule — vitamins_missing

Binary "no vitamin entry today" check, gated by a 12:00 floor.

**Files:**
- Modify: `services/api/app/services/nudges.py`
- Modify: `services/api/tests/test_nudges_engine.py`

- [ ] **Step 1: Write failing tests**

Append to `services/api/tests/test_nudges_engine.py`:

```python
from app.services.nudges import (
    NudgeContext,
    rule_vitamins_missing,
)


def _ctx(
    now_local: datetime,
    *,
    targets: dict | None = None,
    vitamins: int = 0,
    water_oz: float = 0,
    weight: bool = False,
    steps: int | None = 0,
) -> NudgeContext:
    return NudgeContext(
        now_local=now_local,
        targets=targets or {},
        vitamins_count_today=vitamins,
        water_oz_today=water_oz,
        weight_logged_today=weight,
        steps_today=steps,
    )


class TestVitaminsMissing:
    def test_before_floor_silent(self):
        ctx = _ctx(datetime(2026, 4, 27, 11, 59, tzinfo=MT), vitamins=0)
        assert rule_vitamins_missing(ctx) is None

    def test_at_floor_fires(self):
        ctx = _ctx(datetime(2026, 4, 27, 12, 0, tzinfo=MT), vitamins=0)
        nudge = rule_vitamins_missing(ctx)
        assert nudge is not None
        assert nudge.id == "vitamins_missing"
        assert nudge.kind == "vitamin"

    def test_after_floor_with_logged_silent(self):
        ctx = _ctx(datetime(2026, 4, 27, 14, 0, tzinfo=MT), vitamins=1)
        assert rule_vitamins_missing(ctx) is None

    def test_after_floor_zero_logged_fires(self):
        ctx = _ctx(datetime(2026, 4, 27, 14, 0, tzinfo=MT), vitamins=0)
        assert rule_vitamins_missing(ctx) is not None
```

- [ ] **Step 2: Run tests — expect failure**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_engine.py::TestVitaminsMissing -x`
Expected: FAIL — `rule_vitamins_missing` not exported.

- [ ] **Step 3: Implement the rule**

In `services/api/app/services/nudges.py`, append above `RULES: list[Rule] = []`:

```python
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
```

And update the registry line:

```python
RULES: list[Rule] = [
    Rule(
        id="vitamins_missing", kind="vitamin",
        pushable=True, push_at=time(12, 0),
        evaluate=rule_vitamins_missing,
    ),
]
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_engine.py -x`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/nudges.py services/api/tests/test_nudges_engine.py
git commit -m "feat(nudges): vitamins_missing rule"
```

---

## Task 3: Rule — water_below_pace

Pace-based; silent if no target set. Pace formula: `intake < target × elapsed × 0.7`.

**Files:**
- Modify: `services/api/app/services/nudges.py`
- Modify: `services/api/tests/test_nudges_engine.py`

- [ ] **Step 1: Write failing tests**

Append to `services/api/tests/test_nudges_engine.py`:

```python
from app.services.nudges import rule_water_below_pace


class TestWaterBelowPace:
    TARGETS = {"daily_water_oz": 64}

    def test_no_target_silent(self):
        ctx = _ctx(
            datetime(2026, 4, 27, 14, 0, tzinfo=MT),
            targets={}, water_oz=0,
        )
        assert rule_water_below_pace(ctx) is None

    def test_before_floor_silent(self):
        ctx = _ctx(
            datetime(2026, 4, 27, 9, 59, tzinfo=MT),
            targets=self.TARGETS, water_oz=0,
        )
        assert rule_water_below_pace(ctx) is None

    def test_at_pace_silent(self):
        # 1pm: elapsed = 7/16 = 0.4375. Pace target with 0.7 tolerance:
        #   64 * 0.4375 * 0.7 ≈ 19.6oz. Drinking 20oz is just at pace.
        ctx = _ctx(
            datetime(2026, 4, 27, 13, 0, tzinfo=MT),
            targets=self.TARGETS, water_oz=20,
        )
        assert rule_water_below_pace(ctx) is None

    def test_below_pace_fires(self):
        # Same time, but only 10oz consumed → fires.
        ctx = _ctx(
            datetime(2026, 4, 27, 13, 0, tzinfo=MT),
            targets=self.TARGETS, water_oz=10,
        )
        nudge = rule_water_below_pace(ctx)
        assert nudge is not None
        assert nudge.id == "water_below_pace"

    def test_target_zero_silent(self):
        ctx = _ctx(
            datetime(2026, 4, 27, 14, 0, tzinfo=MT),
            targets={"daily_water_oz": 0}, water_oz=0,
        )
        assert rule_water_below_pace(ctx) is None
```

- [ ] **Step 2: Run tests — expect failure**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_engine.py::TestWaterBelowPace -x`
Expected: FAIL — symbol not exported.

- [ ] **Step 3: Implement the rule**

In `services/api/app/services/nudges.py`, after `rule_vitamins_missing`:

```python
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
```

Add to `RULES`:

```python
    Rule(
        id="water_below_pace", kind="water",
        pushable=False, push_at=None,
        evaluate=rule_water_below_pace,
    ),
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_engine.py -x`
Expected: PASS — all water tests pass; previous tests still pass.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/nudges.py services/api/tests/test_nudges_engine.py
git commit -m "feat(nudges): water_below_pace rule"
```

---

## Task 4: Rule — no_weighin

Binary "no Garmin weight reading today", gated by a 10:00 floor.

**Files:**
- Modify: `services/api/app/services/nudges.py`
- Modify: `services/api/tests/test_nudges_engine.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
from app.services.nudges import rule_no_weighin


class TestNoWeighin:
    def test_before_floor_silent(self):
        ctx = _ctx(datetime(2026, 4, 27, 9, 59, tzinfo=MT), weight=False)
        assert rule_no_weighin(ctx) is None

    def test_at_floor_no_weight_fires(self):
        ctx = _ctx(datetime(2026, 4, 27, 10, 0, tzinfo=MT), weight=False)
        nudge = rule_no_weighin(ctx)
        assert nudge is not None
        assert nudge.id == "no_weighin"
        assert nudge.kind == "weight"

    def test_after_floor_weighed_silent(self):
        ctx = _ctx(datetime(2026, 4, 27, 14, 0, tzinfo=MT), weight=True)
        assert rule_no_weighin(ctx) is None
```

- [ ] **Step 2: Run tests — expect failure**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_engine.py::TestNoWeighin -x`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
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
```

Add to `RULES`:

```python
    Rule(
        id="no_weighin", kind="weight",
        pushable=True, push_at=time(10, 0),
        evaluate=rule_no_weighin,
    ),
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_engine.py -x`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/nudges.py services/api/tests/test_nudges_engine.py
git commit -m "feat(nudges): no_weighin rule"
```

---

## Task 5: Rule — steps_below_pace

Pace-based, silent when no daily summary doc exists yet.

**Files:**
- Modify: `services/api/app/services/nudges.py`
- Modify: `services/api/tests/test_nudges_engine.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
from app.services.nudges import rule_steps_below_pace


class TestStepsBelowPace:
    TARGETS = {"step_goal_override": 10000}

    def test_before_floor_silent(self):
        ctx = _ctx(
            datetime(2026, 4, 27, 11, 59, tzinfo=MT),
            targets=self.TARGETS, steps=0,
        )
        assert rule_steps_below_pace(ctx) is None

    def test_steps_none_silent(self):
        # No daily summary doc → can't distinguish 'behind' from 'no data'
        ctx = _ctx(
            datetime(2026, 4, 27, 14, 0, tzinfo=MT),
            targets=self.TARGETS, steps=None,
        )
        assert rule_steps_below_pace(ctx) is None

    def test_no_target_silent(self):
        ctx = _ctx(
            datetime(2026, 4, 27, 14, 0, tzinfo=MT),
            targets={}, steps=0,
        )
        assert rule_steps_below_pace(ctx) is None

    def test_below_pace_fires(self):
        # 2pm: elapsed = 8/16 = 0.5. With 0.6 tolerance:
        #   10000 * 0.5 * 0.6 = 3000. 1000 steps is below → fires.
        ctx = _ctx(
            datetime(2026, 4, 27, 14, 0, tzinfo=MT),
            targets=self.TARGETS, steps=1000,
        )
        nudge = rule_steps_below_pace(ctx)
        assert nudge is not None
        assert nudge.id == "steps_below_pace"

    def test_at_pace_silent(self):
        ctx = _ctx(
            datetime(2026, 4, 27, 14, 0, tzinfo=MT),
            targets=self.TARGETS, steps=3500,
        )
        assert rule_steps_below_pace(ctx) is None
```

- [ ] **Step 2: Run tests — expect failure**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_engine.py::TestStepsBelowPace -x`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
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
```

Add to `RULES`:

```python
    Rule(
        id="steps_below_pace", kind="steps",
        pushable=False, push_at=None,
        evaluate=rule_steps_below_pace,
    ),
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_engine.py -x`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/nudges.py services/api/tests/test_nudges_engine.py
git commit -m "feat(nudges): steps_below_pace rule"
```

---

## Task 6: Rule — bedtime_reminder

Time-of-day window 21:30–22:30 local. Always fires inside the window (no other gating).

**Files:**
- Modify: `services/api/app/services/nudges.py`
- Modify: `services/api/tests/test_nudges_engine.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
from app.services.nudges import rule_bedtime_reminder


class TestBedtimeReminder:
    def test_before_window_silent(self):
        ctx = _ctx(datetime(2026, 4, 27, 21, 29, tzinfo=MT))
        assert rule_bedtime_reminder(ctx) is None

    def test_at_window_start_fires(self):
        ctx = _ctx(datetime(2026, 4, 27, 21, 30, tzinfo=MT))
        nudge = rule_bedtime_reminder(ctx)
        assert nudge is not None
        assert nudge.id == "bedtime_reminder"

    def test_inside_window_fires(self):
        ctx = _ctx(datetime(2026, 4, 27, 22, 0, tzinfo=MT))
        assert rule_bedtime_reminder(ctx) is not None

    def test_at_window_end_silent(self):
        ctx = _ctx(datetime(2026, 4, 27, 22, 30, tzinfo=MT))
        assert rule_bedtime_reminder(ctx) is None

    def test_after_window_silent(self):
        ctx = _ctx(datetime(2026, 4, 27, 23, 0, tzinfo=MT))
        assert rule_bedtime_reminder(ctx) is None
```

- [ ] **Step 2: Run tests — expect failure**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_engine.py::TestBedtimeReminder -x`
Expected: FAIL.

- [ ] **Step 3: Implement**

```python
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
```

Add to `RULES`:

```python
    Rule(
        id="bedtime_reminder", kind="bedtime",
        pushable=True, push_at=time(21, 30),
        evaluate=rule_bedtime_reminder,
    ),
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_engine.py -x`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/nudges.py services/api/tests/test_nudges_engine.py
git commit -m "feat(nudges): bedtime_reminder rule"
```

---

## Task 7: `evaluate_all` — registry runner with fail-open + dismissal filter

Runs every `Rule` from `RULES`, swallows exceptions, filters out dismissed entries.

**Files:**
- Modify: `services/api/app/services/nudges.py`
- Modify: `services/api/tests/test_nudges_engine.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
from app.services.nudges import evaluate_all


class TestEvaluateAll:
    def test_returns_in_registry_order(self):
        # 1pm with no targets → only vitamins doesn't fire (before noon? no, 1pm).
        # vitamins not logged → vitamins fires. weight not logged → weighin fires.
        # No targets → water/steps silent. Bedtime out of window.
        now = datetime(2026, 4, 27, 13, 0, tzinfo=MT)
        ctx = _ctx(now, vitamins=0, weight=False)
        out = evaluate_all(ctx, dismissed_ids=set())
        ids = [n.id for n in out]
        # Registry order: vitamins, water, weighin, steps, bedtime.
        # Water/steps silent (no target), bedtime out of window.
        assert ids == ["vitamins_missing", "no_weighin"]

    def test_dismissed_filtered(self):
        now = datetime(2026, 4, 27, 13, 0, tzinfo=MT)
        ctx = _ctx(now, vitamins=0, weight=False)
        out = evaluate_all(ctx, dismissed_ids={"vitamins_missing"})
        ids = [n.id for n in out]
        assert ids == ["no_weighin"]

    def test_failing_rule_does_not_break_others(self, monkeypatch):
        # Inject a rule that raises; sibling rules must still run.
        from app.services import nudges

        def boom(ctx):
            raise ValueError("kaboom")

        rogue = nudges.Rule(
            id="rogue", kind="x", pushable=False, push_at=None, evaluate=boom,
        )
        monkeypatch.setattr(nudges, "RULES", [rogue, *nudges.RULES])
        now = datetime(2026, 4, 27, 13, 0, tzinfo=MT)
        ctx = _ctx(now, vitamins=0, weight=False)
        out = evaluate_all(ctx, dismissed_ids=set())
        ids = [n.id for n in out]
        # Rogue swallowed; siblings still fire in order.
        assert ids == ["vitamins_missing", "no_weighin"]
```

- [ ] **Step 2: Run tests — expect failure**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_engine.py::TestEvaluateAll -x`
Expected: FAIL — `evaluate_all` not defined.

- [ ] **Step 3: Implement**

In `services/api/app/services/nudges.py`, append at the bottom:

```python
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
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_engine.py -x`
Expected: PASS — all engine tests green.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/nudges.py services/api/tests/test_nudges_engine.py
git commit -m "feat(nudges): evaluate_all with fail-open + dismissal filter"
```

---

## Task 8: `build_context` — gather everything from Mongo in one pass

Reads targets, today's vitamin entries, today's water total, today's weight, today's steps, and assembles a `NudgeContext`. All reads scoped to the user's local-day window.

**Files:**
- Modify: `services/api/app/services/nudges.py`
- Modify: `services/api/tests/test_nudges_engine.py`

- [ ] **Step 1: Write failing tests**

Append:

```python
import os

from app.models.food import Food, Macros, MealEntry
from app.models.metrics import DailySummary, Weight
from app.services.food_repo import FoodRepo
from app.services.metrics_repo import MetricsRepo
from app.services.nudges import build_context


@pytest.fixture
def mt_tz(monkeypatch):
    monkeypatch.setenv("TZ", "America/Denver")
    return ZoneInfo("America/Denver")


class TestBuildContext:
    async def test_empty_db_safe_defaults(self, mock_db, mt_tz):
        now_utc = datetime(2026, 4, 27, 19, 0, tzinfo=ZoneInfo("UTC"))  # 1pm MT
        ctx = await build_context(mock_db, now_utc=now_utc)
        assert ctx.targets == {}
        assert ctx.vitamins_count_today == 0
        assert ctx.water_oz_today == 0
        assert ctx.weight_logged_today is False
        assert ctx.steps_today is None
        # now_local is 1pm in Denver
        assert ctx.now_local.hour == 13

    async def test_reads_targets(self, mock_db, mt_tz):
        await mock_db["user_profile"].update_one(
            {"_id": "targets"},
            {"$set": {"daily_water_oz": 64, "step_goal_override": 10000}},
            upsert=True,
        )
        now_utc = datetime(2026, 4, 27, 19, 0, tzinfo=ZoneInfo("UTC"))
        ctx = await build_context(mock_db, now_utc=now_utc)
        assert ctx.targets["daily_water_oz"] == 64
        assert ctx.targets["step_goal_override"] == 10000

    async def test_counts_vitamins_today(self, mock_db, mt_tz):
        repo = FoodRepo(mock_db)
        # seed the vitamins food
        food = await repo.upsert_food(Food(
            name="Vitamins", category="supplement",
            serving_g=1, serving_label="1", per_serving=Macros(), source="builtin",
        ))
        await repo.insert_entry(MealEntry(
            ts=datetime(2026, 4, 27, 15, 0, tzinfo=ZoneInfo("UTC")),  # 9am MT
            food_id=food["id"], food_name="Vitamins",
            food_category="supplement", quantity_g=1, servings=1,
            slot="supplement", macros=Macros(),
        ))
        now_utc = datetime(2026, 4, 27, 19, 0, tzinfo=ZoneInfo("UTC"))
        ctx = await build_context(mock_db, now_utc=now_utc)
        assert ctx.vitamins_count_today == 1

    async def test_sums_water_today(self, mock_db, mt_tz):
        repo = FoodRepo(mock_db)
        food = await repo.upsert_food(Food(
            name="Water", category="drink",
            serving_g=29.5735 * 8, serving_label="cup",
            per_serving=Macros(), source="builtin",
        ))
        # 16oz = 16 * 29.5735g
        await repo.insert_entry(MealEntry(
            ts=datetime(2026, 4, 27, 15, 0, tzinfo=ZoneInfo("UTC")),
            food_id=food["id"], food_name="Water", food_category="drink",
            quantity_g=16 * 29.5735, servings=2.0,
            slot="snack", macros=Macros(),
        ))
        now_utc = datetime(2026, 4, 27, 19, 0, tzinfo=ZoneInfo("UTC"))
        ctx = await build_context(mock_db, now_utc=now_utc)
        assert ctx.water_oz_today == pytest.approx(16, abs=0.5)

    async def test_detects_weight_today(self, mock_db, mt_tz):
        mrepo = MetricsRepo(mock_db)
        await mrepo.insert_weight(Weight(
            ts=datetime(2026, 4, 27, 14, 0, tzinfo=ZoneInfo("UTC")),  # 8am MT
            kg=80.0, raw={}, source="garmin", source_id="x",
        ))
        now_utc = datetime(2026, 4, 27, 19, 0, tzinfo=ZoneInfo("UTC"))
        ctx = await build_context(mock_db, now_utc=now_utc)
        assert ctx.weight_logged_today is True

    async def test_reads_steps_today(self, mock_db, mt_tz):
        mrepo = MetricsRepo(mock_db)
        await mrepo.insert_daily_summary(DailySummary(
            ts=datetime(2026, 4, 27, 14, 0, tzinfo=ZoneInfo("UTC")),
            steps=4200, step_goal=10000,
            distance_m=None, active_kcal=None, total_kcal=None,
            resting_hr=None, intensity_minutes=None, floors_climbed=None,
            raw={}, source="garmin", source_id="ds-1",
        ))
        now_utc = datetime(2026, 4, 27, 19, 0, tzinfo=ZoneInfo("UTC"))
        ctx = await build_context(mock_db, now_utc=now_utc)
        assert ctx.steps_today == 4200
```

> **Note:** these are async tests — pytest-asyncio is already configured in this repo (see existing `test_vitamins.py`). The `mock_db` fixture comes from `conftest.py`.

- [ ] **Step 2: Run tests — expect failure**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_engine.py::TestBuildContext -x`
Expected: FAIL — `build_context` not defined.

- [ ] **Step 3: Implement**

In `services/api/app/services/nudges.py`, add at the top of imports:

```python
import os
from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

from pymongo.asynchronous.database import AsyncDatabase
```

Append at the bottom of the module:

```python
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
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_engine.py -x`
Expected: PASS — all engine + context tests green.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/nudges.py services/api/tests/test_nudges_engine.py
git commit -m "feat(nudges): build_context — snapshot today's signals"
```

---

## Task 9: Dismissal helpers — `nudge_dismissals` collection

Per-day Mongo doc keyed `<user>_<YYYY-MM-DD>`. This is a single-user app so the user prefix is a constant placeholder.

**Files:**
- Create: `services/api/app/services/nudge_dismissals.py`
- Modify: `services/api/tests/test_nudges_engine.py`

- [ ] **Step 1: Write failing tests**

Append to `services/api/tests/test_nudges_engine.py`:

```python
from app.services.nudge_dismissals import (
    end_of_day_local,
    get_active_dismissals,
    record_dismissal,
)


class TestDismissals:
    async def test_empty_returns_empty_set(self, mock_db, mt_tz):
        now_utc = datetime(2026, 4, 27, 19, 0, tzinfo=ZoneInfo("UTC"))
        ids = await get_active_dismissals(mock_db, now_utc=now_utc)
        assert ids == set()

    async def test_record_then_read(self, mock_db, mt_tz):
        now_utc = datetime(2026, 4, 27, 19, 0, tzinfo=ZoneInfo("UTC"))
        await record_dismissal(
            mock_db, nudge_id="vitamins_missing",
            until="end_of_day", now_utc=now_utc,
        )
        ids = await get_active_dismissals(mock_db, now_utc=now_utc)
        assert ids == {"vitamins_missing"}

    async def test_expired_dismissal_not_active(self, mock_db, mt_tz):
        # Record a dismissal that's already in the past.
        now_utc = datetime(2026, 4, 27, 19, 0, tzinfo=ZoneInfo("UTC"))
        past = datetime(2026, 4, 27, 14, 0, tzinfo=ZoneInfo("UTC"))
        await record_dismissal(
            mock_db, nudge_id="water_below_pace",
            until=past.isoformat(), now_utc=now_utc,
        )
        ids = await get_active_dismissals(mock_db, now_utc=now_utc)
        assert ids == set()

    async def test_end_of_day_local(self, mt_tz):
        now_utc = datetime(2026, 4, 27, 19, 0, tzinfo=ZoneInfo("UTC"))  # 1pm MT
        eod = end_of_day_local(now_utc)
        # End-of-day for Apr 27 in Denver → Apr 28 at 06:00 UTC (MDT is UTC-6).
        assert eod.tzinfo is not None
        assert eod.year == 2026 and eod.month == 4 and eod.day == 28
```

- [ ] **Step 2: Run tests — expect failure**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_engine.py::TestDismissals -x`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement**

Create `services/api/app/services/nudge_dismissals.py`:

```python
"""Per-day dismissal overlay for prescriptive nudges.

One Mongo doc per local-date, shape:

    { _id: "<user>_<YYYY-MM-DD>",
      entries: { vitamins_missing: <iso utc ts>, ... } }

`<user>` is a constant placeholder — this app is single-user and we don't
yet model accounts. When that changes, replace USER_KEY with a real user id.
"""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Literal

from pymongo.asynchronous.database import AsyncDatabase

from app.services.nudges import _local_tz

USER_KEY = "default"


def _doc_id(now_utc: datetime) -> str:
    local_date = now_utc.astimezone(_local_tz()).date().isoformat()
    return f"{USER_KEY}_{local_date}"


def end_of_day_local(now_utc: datetime) -> datetime:
    """Local end-of-day (== start of *tomorrow*) for the date that contains `now_utc`."""
    tz = _local_tz()
    local = now_utc.astimezone(tz)
    next_local_midnight = datetime.combine(
        local.date() + timedelta(days=1), time.min, tzinfo=tz,
    )
    return next_local_midnight.astimezone(UTC)


def _resolve_until(
    until: Literal["end_of_day"] | str,
    now_utc: datetime,
) -> datetime:
    if until == "end_of_day":
        return end_of_day_local(now_utc)
    # ISO timestamp string
    parsed = datetime.fromisoformat(until)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


async def record_dismissal(
    db: AsyncDatabase,
    *,
    nudge_id: str,
    until: Literal["end_of_day"] | str,
    now_utc: datetime | None = None,
) -> None:
    if now_utc is None:
        now_utc = datetime.now(UTC)
    until_dt = _resolve_until(until, now_utc)
    await db["nudge_dismissals"].update_one(
        {"_id": _doc_id(now_utc)},
        {"$set": {f"entries.{nudge_id}": until_dt}},
        upsert=True,
    )


async def get_active_dismissals(
    db: AsyncDatabase,
    *,
    now_utc: datetime | None = None,
) -> set[str]:
    if now_utc is None:
        now_utc = datetime.now(UTC)
    doc = await db["nudge_dismissals"].find_one({"_id": _doc_id(now_utc)})
    if not doc:
        return set()
    entries = doc.get("entries") or {}
    out: set[str] = set()
    for nudge_id, until in entries.items():
        if isinstance(until, datetime):
            until_dt = until if until.tzinfo else until.replace(tzinfo=UTC)
        else:
            try:
                until_dt = datetime.fromisoformat(str(until))
                if until_dt.tzinfo is None:
                    until_dt = until_dt.replace(tzinfo=UTC)
            except Exception:
                continue
        if until_dt > now_utc:
            out.add(nudge_id)
    return out
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_engine.py -x`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/nudge_dismissals.py services/api/tests/test_nudges_engine.py
git commit -m "feat(nudges): per-day dismissal overlay"
```

---

## Task 10: HTTP routes — `GET /nudges` and `POST /nudges/dismiss`

Wire the engine into FastAPI.

**Files:**
- Create: `services/api/app/routers/nudges.py`
- Create: `services/api/tests/test_nudges_router.py`
- Modify: `services/api/app/main.py`

- [ ] **Step 1: Write failing router tests**

Create `services/api/tests/test_nudges_router.py`:

```python
"""Endpoint tests for /nudges."""
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest


HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture(autouse=True)
def fix_tz(monkeypatch):
    monkeypatch.setenv("TZ", "America/Denver")


class TestGetNudges:
    async def test_requires_api_key(self, client):
        r = await client.get("/nudges")
        assert r.status_code in (401, 403)

    async def test_empty_db_returns_some_nudges(self, client):
        # Empty DB at default 'now' will likely return at least one nudge
        # depending on time — just assert shape.
        r = await client.get("/nudges", headers=HEADERS)
        assert r.status_code == 200
        body = r.json()
        assert "nudges" in body
        assert "generated_at" in body
        assert isinstance(body["nudges"], list)


class TestDismiss:
    async def test_records_dismissal(self, client, mock_db):
        r = await client.post(
            "/nudges/dismiss",
            headers=HEADERS,
            json={"nudge_id": "vitamins_missing", "until": "end_of_day"},
        )
        assert r.status_code == 200
        # Doc was written
        doc = await mock_db["nudge_dismissals"].find_one({})
        assert doc is not None
        assert "vitamins_missing" in (doc.get("entries") or {})

    async def test_unknown_nudge_id_is_noop_200(self, client):
        r = await client.post(
            "/nudges/dismiss",
            headers=HEADERS,
            json={"nudge_id": "made_up", "until": "end_of_day"},
        )
        assert r.status_code == 200

    async def test_malformed_until_is_422(self, client):
        r = await client.post(
            "/nudges/dismiss",
            headers=HEADERS,
            json={"nudge_id": "x"},  # missing 'until'
        )
        assert r.status_code == 422

    async def test_dismissed_nudge_filtered_from_get(self, client, mock_db):
        # Dismiss vitamins.
        await client.post(
            "/nudges/dismiss",
            headers=HEADERS,
            json={"nudge_id": "vitamins_missing", "until": "end_of_day"},
        )
        r = await client.get("/nudges", headers=HEADERS)
        ids = [n["id"] for n in r.json()["nudges"]]
        assert "vitamins_missing" not in ids
```

- [ ] **Step 2: Run tests — expect failure**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_router.py -x`
Expected: FAIL — `/nudges` not routed.

- [ ] **Step 3: Implement the router**

Create `services/api/app/routers/nudges.py`:

```python
"""Prescriptive nudges HTTP surface.

GET /nudges            → currently-firing nudges for the local 'today'
POST /nudges/dismiss   → suppress a nudge for the rest of today (or until ts)
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.auth import require_api_key
from app.services.nudge_dismissals import get_active_dismissals, record_dismissal
from app.services.nudges import build_context, evaluate_all

router = APIRouter(prefix="/nudges", dependencies=[Depends(require_api_key)])


@router.get("")
async def get_nudges(request: Request) -> dict:
    db = request.app.state.db
    now_utc = datetime.now(UTC)
    ctx = await build_context(db, now_utc=now_utc)
    dismissed = await get_active_dismissals(db, now_utc=now_utc)
    fired = evaluate_all(ctx, dismissed_ids=dismissed)
    return {
        "nudges": [asdict(n) for n in fired],
        "generated_at": now_utc.isoformat(),
    }


class DismissReq(BaseModel):
    nudge_id: str = Field(min_length=1, max_length=64)
    until: Literal["end_of_day"] | str


@router.post("/dismiss")
async def dismiss_nudge(req: DismissReq, request: Request) -> dict:
    db = request.app.state.db
    await record_dismissal(db, nudge_id=req.nudge_id, until=req.until)
    return {"ok": True}
```

- [ ] **Step 4: Wire into `main.py`**

In `services/api/app/main.py`, modify the import block and `include_router` calls. Replace:

```python
    from app.routers import (
        admin,
        auth,
        coach,
        foods,
        meals,
        metrics,
        profile,
        push,
        vitamins,
        water,
        workouts,
    )
```

with:

```python
    from app.routers import (
        admin,
        auth,
        coach,
        foods,
        meals,
        metrics,
        nudges,
        profile,
        push,
        vitamins,
        water,
        workouts,
    )
```

And in the `include_router` block, after `app.include_router(vitamins.router)`, add:

```python
    app.include_router(nudges.router)
```

- [ ] **Step 5: Run tests — expect pass**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_router.py tests/test_nudges_engine.py -x`
Expected: PASS — all router + engine tests green.

- [ ] **Step 6: Run the full test suite to catch regressions**

Run: `cd services/api && .venv/bin/pytest`
Expected: PASS — all tests (including pre-existing).

- [ ] **Step 7: Commit**

```bash
git add services/api/app/routers/nudges.py services/api/app/main.py services/api/tests/test_nudges_router.py
git commit -m "feat(nudges): GET /nudges and POST /nudges/dismiss"
```

---

## Task 11: Push tick — pure function

A pure function `nudges_push_tick(now_utc, settings, db)` that:
1. Builds context.
2. Reads dismissals.
3. Evaluates only rules whose `push_at` matches the current local-time bucket (±5 min grace).
4. Filters out dismissed.
5. Sends one web push per fired nudge.

Wire it into the scheduler in Task 12.

**Files:**
- Modify: `services/api/app/services/nudges.py`
- Create: `services/api/tests/test_nudges_scheduler.py`

- [ ] **Step 1: Write failing tests**

Create `services/api/tests/test_nudges_scheduler.py`:

```python
"""Push-tick tests for the nudges scheduler."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.services.nudges import nudges_push_tick


@pytest.fixture
def fix_tz(monkeypatch):
    monkeypatch.setenv("TZ", "America/Denver")


@pytest.fixture
def settings():
    return Settings(mongo_url="mongodb://fake", mongo_db="testdb", api_key="test-key")


@pytest.fixture
def mock_send_push(monkeypatch):
    sender = AsyncMock(return_value={"sent": 1, "pruned": 0, "failed": 0, "subscriptions": 1})
    monkeypatch.setattr("app.services.nudges.send_push", sender)
    return sender


class TestPushTick:
    async def test_fires_only_matching_bucket(self, mock_db, settings, fix_tz, mock_send_push):
        # 12:00 MT in UTC is 18:00 UTC (MDT = UTC-6)
        now_utc = datetime(2026, 4, 27, 18, 0, tzinfo=UTC)
        # Nothing seeded → vitamins_missing fires (push_at = 12:00).
        await nudges_push_tick(now_utc, settings, mock_db)
        assert mock_send_push.await_count == 1
        # Title should match the vitamins nudge title.
        payload = mock_send_push.await_args.args[2]
        assert payload["title"] == "Vitamins not taken yet"

    async def test_dismissed_does_not_push(self, mock_db, settings, fix_tz, mock_send_push):
        from app.services.nudge_dismissals import record_dismissal
        now_utc = datetime(2026, 4, 27, 18, 0, tzinfo=UTC)  # 12pm MT
        await record_dismissal(
            mock_db, nudge_id="vitamins_missing", until="end_of_day", now_utc=now_utc,
        )
        await nudges_push_tick(now_utc, settings, mock_db)
        assert mock_send_push.await_count == 0

    async def test_off_bucket_no_push(self, mock_db, settings, fix_tz, mock_send_push):
        # 11:00 MT → no bucket matches.
        now_utc = datetime(2026, 4, 27, 17, 0, tzinfo=UTC)
        await nudges_push_tick(now_utc, settings, mock_db)
        assert mock_send_push.await_count == 0

    async def test_grace_window_5_min(self, mock_db, settings, fix_tz, mock_send_push):
        # 12:04 MT — within ±5 min grace of 12:00 bucket.
        now_utc = datetime(2026, 4, 27, 18, 4, tzinfo=UTC)
        await nudges_push_tick(now_utc, settings, mock_db)
        assert mock_send_push.await_count == 1

    async def test_outside_grace_window(self, mock_db, settings, fix_tz, mock_send_push):
        # 12:06 MT — outside ±5 min grace.
        now_utc = datetime(2026, 4, 27, 18, 6, tzinfo=UTC)
        await nudges_push_tick(now_utc, settings, mock_db)
        assert mock_send_push.await_count == 0
```

- [ ] **Step 2: Run tests — expect failure**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_scheduler.py -x`
Expected: FAIL — `nudges_push_tick` not defined.

- [ ] **Step 3: Implement**

In `services/api/app/services/nudges.py`, add to imports near the top:

```python
from app.config import Settings
from app.services.push import send_push
```

Append at the bottom:

```python
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
    from app.services.nudge_dismissals import get_active_dismissals  # avoid cycle

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
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/api && .venv/bin/pytest tests/test_nudges_scheduler.py tests/test_nudges_engine.py tests/test_nudges_router.py -x`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/nudges.py services/api/tests/test_nudges_scheduler.py
git commit -m "feat(nudges): push-tick function with bucket grace window"
```

---

## Task 12: Wire the push tick into APScheduler; remove old vitamin job

The standalone `_vitamin_reminder_run` is replaced by the unified nudges push tick (which already pushes vitamins at 12:00). The old config var `vitamin_reminder_local` becomes inert.

**Files:**
- Modify: `services/api/app/services/scheduler.py`
- Modify: `services/api/app/config.py`

- [ ] **Step 1: Read the current scheduler to know what you're editing**

Run: `cat services/api/app/services/scheduler.py`
Expected output: contains `_vitamin_reminder_run`, `count_vitamins_today` import, and a `vit = settings.vitamin_reminder_time` block at the bottom of `build_scheduler`.

- [ ] **Step 2: Edit `services/scheduler.py` — remove vitamin job, add nudges jobs**

Replace the entire contents of `services/api/app/services/scheduler.py` with:

```python
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
from datetime import UTC, datetime, time, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pymongo.asynchronous.database import AsyncDatabase

from app.config import Settings
from app.services.coach import generate_insight
from app.services.coach_weekly import generate_weekly_review
from app.services.food_repo import FoodRepo
from app.services.nudges import PUSH_BUCKETS, nudges_push_tick
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


async def _nudges_push_run(settings: Settings, db: AsyncDatabase) -> None:
    try:
        await nudges_push_tick(datetime.now(UTC), settings, db)
    except Exception:
        logger.exception("nudges push tick: failed")


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
```

- [ ] **Step 3: Mark `vitamin_reminder_local` deprecated in `config.py`**

In `services/api/app/config.py`, change the comment block above
`vitamin_reminder_local` to:

```python
    # DEPRECATED: superseded by the unified nudges push tick (see
    # services/nudges.py PUSH_BUCKETS). Kept here only so existing .env
    # files don't break on import. The value is now ignored.
    vitamin_reminder_local: str = "10:00"
```

- [ ] **Step 4: Run the full test suite**

Run: `cd services/api && .venv/bin/pytest`
Expected: PASS — all tests, including pre-existing.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/scheduler.py services/api/app/config.py
git commit -m "feat(nudges): wire push-tick cron, retire standalone vitamin job"
```

---

## Task 13: Frontend — types + API client

**Files:**
- Modify: `services/web/src/api/types.ts`
- Modify: `services/web/src/api/client.ts`

- [ ] **Step 1: Locate the right place to add types**

Run: `grep -n "VitaminsToday\|WaterToday" services/web/src/api/types.ts | head -5`
Expected: shows where existing today-shape types are defined.

- [ ] **Step 2: Add types**

Open `services/web/src/api/types.ts` and append:

```ts
export type NudgeSeverity = "info" | "warn";

export interface FiredNudge {
  id: string;
  kind: string;
  severity: NudgeSeverity;
  title: string;
  body: string;
  dismissable: boolean;
}

export interface NudgesResponse {
  nudges: FiredNudge[];
  generated_at: string;
}

export interface DismissNudgeReq {
  nudge_id: string;
  until: "end_of_day" | string;
}
```

- [ ] **Step 3: Add API methods**

In `services/web/src/api/client.ts`, find the existing `vitamins` block (search for `vitaminsToday`) and append in the `export const api = { ... }` literal, near the bottom (before the closing `}`):

```ts
  // nudges
  fetchNudges: () => get<NudgesResponse>("/nudges"),
  dismissNudge: (req: DismissNudgeReq) => post<{ ok: true }>("/nudges/dismiss", req),
```

Update the type import at the top of `client.ts` to include the new types:

```ts
import type {
  Summary, WeightPoint, SleepPoint, HRVPoint, RHRPoint, VO2MaxPoint, DailySummaryPoint, Workout,
  Food, MealEntry, MealTemplate, MealSlot, TodayTotals, StepsToday, CoachInsight, CoachRecentEntry,
  CoachFeedback, CoachFeedbackRating, SyncStatus, UserTargets,
  WaterToday, VitaminsToday, ParsedFoodItem,
  NudgesResponse, DismissNudgeReq,
} from "./types";
```

- [ ] **Step 4: Verify FE typechecks**

Run: `cd services/web && npm run typecheck 2>&1 || npx tsc --noEmit`
Expected: zero errors.

- [ ] **Step 5: Commit**

```bash
git add services/web/src/api/types.ts services/web/src/api/client.ts
git commit -m "feat(nudges): FE API client + types"
```

---

## Task 14: Frontend — `NudgesCard` component (with tests)

**Files:**
- Create: `services/web/src/components/NudgesCard.tsx`
- Create: `services/web/src/components/NudgesCard.test.tsx`

- [ ] **Step 1: Write failing tests**

Create `services/web/src/components/NudgesCard.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { NudgesCard } from "./NudgesCard";

vi.mock("../api/client", () => ({
  api: {
    fetchNudges: vi.fn(),
    dismissNudge: vi.fn(),
  },
}));

import { api } from "../api/client";

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>;
}

describe("NudgesCard", () => {
  it("renders nothing when no nudges fire", async () => {
    (api.fetchNudges as any).mockResolvedValue({ nudges: [], generated_at: "x" });
    const { container } = render(wrap(<NudgesCard />));
    await waitFor(() => expect(api.fetchNudges).toHaveBeenCalled());
    expect(container.textContent ?? "").toBe("");
  });

  it("renders a row per fired nudge", async () => {
    (api.fetchNudges as any).mockResolvedValue({
      nudges: [
        { id: "vitamins_missing", kind: "vitamin", severity: "warn",
          title: "Vitamins not taken yet", body: "It's past noon.",
          dismissable: true },
        { id: "no_weighin", kind: "weight", severity: "info",
          title: "No weigh-in yet", body: "Step on the scale.",
          dismissable: true },
      ],
      generated_at: "x",
    });
    render(wrap(<NudgesCard />));
    expect(await screen.findByText("Vitamins not taken yet")).toBeTruthy();
    expect(screen.getByText("No weigh-in yet")).toBeTruthy();
  });

  it("dismisses a nudge optimistically", async () => {
    (api.fetchNudges as any).mockResolvedValue({
      nudges: [
        { id: "vitamins_missing", kind: "vitamin", severity: "warn",
          title: "Vitamins not taken yet", body: "x", dismissable: true },
      ],
      generated_at: "x",
    });
    (api.dismissNudge as any).mockResolvedValue({ ok: true });

    render(wrap(<NudgesCard />));
    const row = await screen.findByText("Vitamins not taken yet");
    expect(row).toBeTruthy();
    const dismiss = screen.getByLabelText("dismiss vitamins_missing");
    fireEvent.click(dismiss);
    await waitFor(() =>
      expect(api.dismissNudge).toHaveBeenCalledWith({
        nudge_id: "vitamins_missing", until: "end_of_day",
      }),
    );
  });
});
```

- [ ] **Step 2: Run tests — expect failure**

Run: `cd services/web && npm test -- --run NudgesCard`
Expected: FAIL — `NudgesCard` not found.

- [ ] **Step 3: Implement the component**

Create `services/web/src/components/NudgesCard.tsx`:

```tsx
/**
 * Top-of-dashboard prescriptive nudges.
 *
 * Stateless source of truth lives on the server. We just render whatever
 * GET /nudges returned and call POST /nudges/dismiss on the × button. The
 * card hides itself entirely when no nudges fire — absence is the reward.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { FiredNudge } from "../api/types";

const ICONS: Record<string, string> = {
  vitamin: "💊",
  water: "💧",
  weight: "⚖️",
  steps: "🚶",
  bedtime: "🌙",
};

const SEVERITY_RING: Record<string, string> = {
  warn: "border-amber-700/60",
  info: "border-neutral-800",
};

export function NudgesCard() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["nudges"],
    queryFn: api.fetchNudges,
    refetchInterval: 60_000,
  });

  const dismiss = useMutation({
    mutationFn: (nudge_id: string) =>
      api.dismissNudge({ nudge_id, until: "end_of_day" }),
    onMutate: async (nudge_id) => {
      await qc.cancelQueries({ queryKey: ["nudges"] });
      const prev = qc.getQueryData<{ nudges: FiredNudge[] }>(["nudges"]);
      if (prev) {
        qc.setQueryData(["nudges"], {
          ...prev,
          nudges: prev.nudges.filter((n) => n.id !== nudge_id),
        });
      }
      return { prev };
    },
    onError: (_e, _id, ctx) => {
      if (ctx?.prev) qc.setQueryData(["nudges"], ctx.prev);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["nudges"] });
    },
  });

  const nudges = q.data?.nudges ?? [];
  if (q.isLoading || q.isError || nudges.length === 0) return null;

  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-4 space-y-3">
      <div className="text-xs uppercase tracking-wide text-neutral-400">Today</div>
      <ul className="space-y-2">
        {nudges.map((n) => (
          <li
            key={n.id}
            className={`flex items-start gap-3 rounded-lg border ${
              SEVERITY_RING[n.severity] ?? SEVERITY_RING.info
            } bg-neutral-900/60 px-3 py-2`}
          >
            <span aria-hidden className="text-xl leading-none mt-0.5">
              {ICONS[n.kind] ?? "•"}
            </span>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium">{n.title}</div>
              <div className="text-xs text-neutral-400">{n.body}</div>
            </div>
            {n.dismissable && (
              <button
                aria-label={`dismiss ${n.id}`}
                className="text-neutral-500 hover:text-neutral-200 px-2 py-1 text-sm"
                onClick={() => dismiss.mutate(n.id)}
              >
                ✕
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 4: Run tests — expect pass**

Run: `cd services/web && npm test -- --run NudgesCard`
Expected: PASS — 3 tests pass.

- [ ] **Step 5: Run full FE test suite**

Run: `cd services/web && npm test -- --run`
Expected: PASS — all tests, including pre-existing.

- [ ] **Step 6: Commit**

```bash
git add services/web/src/components/NudgesCard.tsx services/web/src/components/NudgesCard.test.tsx
git commit -m "feat(nudges): NudgesCard component"
```

---

## Task 15: Mount `NudgesCard` at top of Dashboard

**Files:**
- Modify: `services/web/src/pages/Dashboard.tsx`

- [ ] **Step 1: Find the right insertion point**

Run: `grep -n "VitaminsCard\|CoachCard" services/web/src/pages/Dashboard.tsx | head -10`
Expected: shows imports and a render site for those cards.

- [ ] **Step 2: Add the import**

In `services/web/src/pages/Dashboard.tsx`, add to the existing imports near the top of the file:

```ts
import { NudgesCard } from "../components/NudgesCard";
```

- [ ] **Step 3: Render `<NudgesCard />` near the top of the Today tab**

In `Dashboard.tsx`, find the JSX where today's main cards are rendered (look for the first `<CoachCard` or `<VitaminsCard` mount inside the Today tab). Mount `<NudgesCard />` immediately above it, e.g.:

```tsx
<NudgesCard />
<CoachCard ... />
<VitaminsCard />
...
```

If you're not sure which tab — run: `grep -n "VitaminsCard\|CoachCard" services/web/src/pages/Dashboard.tsx` to see the existing render lines, and place `<NudgesCard />` directly above the first card mount in the same JSX block.

- [ ] **Step 4: Build the FE to verify**

Run: `cd services/web && npm run build`
Expected: build succeeds with no TS errors.

- [ ] **Step 5: Commit**

```bash
git add services/web/src/pages/Dashboard.tsx
git commit -m "feat(nudges): mount NudgesCard atop Dashboard"
```

---

## Task 16: Final integration check + push

Run all tests + a Docker build to make sure the bundled image still produces.

- [ ] **Step 1: Run all backend tests**

Run: `cd services/api && .venv/bin/pytest -q`
Expected: every test passes.

- [ ] **Step 2: Run all frontend tests**

Run: `cd services/web && npm test -- --run`
Expected: every test passes.

- [ ] **Step 3: Lint / typecheck (if configured)**

Run: `cd services/api && .venv/bin/ruff check . 2>/dev/null || true`
Run: `cd services/web && npx tsc --noEmit`
Expected: no errors. (Ruff is optional — only fail on TS.)

- [ ] **Step 4: Docker build sanity-check**

Run: `cd /home/jvogel/src/personal/hack-the-body && docker build -t hack-the-body-app:plan-check -f services/api/Dockerfile . 2>&1 | tail -20`
Expected: build completes successfully.

- [ ] **Step 5: Push to master**

The repo's CLAUDE.md auto-commits when tests/lint/typecheck are green. Push:

```bash
git log --oneline -20    # eyeball the new commits
git push origin master   # CI builds, Watchtower picks up
```

Expected: successful push. CI run begins on GHA.

- [ ] **Step 6: Eyeball the deployed app**

After CI passes (~3 min) and Watchtower restart cycle (~1 min):

- Visit `http://hd:8080/` — `NudgesCard` should appear at the top *if* the current local time triggers any rule (most likely: bedtime at 21:30+, or vitamins/weigh-in if not done).
- Click × on a fired nudge. It should disappear and not return on refresh.
- If outside any firing window, the card correctly renders nothing.

---

## Self-Review (run after writing the plan)

- **Spec coverage:**
  - Spec §"v1 nudge list" → Tasks 2–6 (one per rule) ✓
  - Spec §Architecture → Tasks 1, 7, 8 (engine + registry + context) ✓
  - Spec §Components — `nudges.py` → Task 1; `routers/nudges.py` → Task 10; `nudge_dismissals` collection → Task 9; push cron → Tasks 11–12; `NudgesCard.tsx` → Task 14; Dashboard mount → Task 15; FE client → Task 13 ✓
  - Spec §Data flow — dashboard load (Task 10), dismissal (Tasks 9, 10, 14), push tick (Tasks 11, 12), day rollover (Task 9 doc-id keying) ✓
  - Spec §Error handling — fail-open per-rule (Task 7); missing data graceful (Task 8 + per-rule tasks); unknown nudge_id 200 (Task 10); 5-min push grace (Task 11); FE renders null on error (Task 14) ✓
  - Spec §Testing — every described test category has a step ✓
- **Placeholder scan:** none found.
- **Type consistency:** `FiredNudge`, `NudgeContext`, `Rule`, `evaluate_all`, `build_context`, `nudges_push_tick`, `record_dismissal`, `get_active_dismissals`, `end_of_day_local` — all defined exactly once and used consistently across tasks. FE types `FiredNudge`, `NudgesResponse`, `DismissNudgeReq` defined in Task 13 and consumed in Task 14.
