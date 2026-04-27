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
