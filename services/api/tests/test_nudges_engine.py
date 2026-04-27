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
