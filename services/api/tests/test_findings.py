"""Unit tests for the coach Findings pipeline.

Pure functions over plain dicts — no Mongo here. The `build_findings`
test (later) covers the integration over real repos.
"""
from datetime import UTC, datetime, timedelta

import pytest

from app.services.coach.context import anomaly_flag, delta, trend


def _series(values: list[float], *, start: datetime | None = None) -> list[dict]:
    """Build a list of {ts, value} dicts spaced one day apart, oldest first."""
    if start is None:
        start = datetime(2026, 5, 1, tzinfo=UTC)
    return [
        {"ts": start + timedelta(days=i), "value": v}
        for i, v in enumerate(values)
    ]


def test_trend_returns_avg_and_slope_for_simple_series():
    series = _series([60.0, 62.0, 64.0, 66.0, 68.0, 70.0, 72.0])
    out = trend(series, value_key="value", window_days=7)
    assert out["count"] == 7
    assert out["avg"] == pytest.approx(66.0, abs=0.01)
    # Slope is "per day": rising 2 units/day across 7 points.
    assert out["slope_per_day"] == pytest.approx(2.0, abs=0.01)
    assert out["first"] == 60.0
    assert out["last"] == 72.0


def test_trend_handles_empty_series():
    out = trend([], value_key="value", window_days=7)
    assert out == {
        "count": 0, "avg": None, "slope_per_day": None,
        "first": None, "last": None,
    }


def test_trend_ignores_missing_values():
    series = _series([60.0, 0.0, 64.0])  # placeholder for missing
    series[1]["value"] = None
    out = trend(series, value_key="value", window_days=7)
    assert out["count"] == 2
    assert out["avg"] == pytest.approx(62.0, abs=0.01)
