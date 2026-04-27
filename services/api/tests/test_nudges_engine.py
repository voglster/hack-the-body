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
