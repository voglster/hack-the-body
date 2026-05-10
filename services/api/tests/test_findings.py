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


def test_delta_computes_window_vs_baseline():
    # Recent 7d avg 70, prior 30d avg 60 → +10 absolute, +16.7%.
    recent = _series([70.0] * 7)
    prior = _series([60.0] * 30)
    out = delta(recent, prior, value_key="value")
    assert out["recent_avg"] == 70.0
    assert out["prior_avg"] == 60.0
    assert out["abs"] == pytest.approx(10.0, abs=0.01)
    assert out["pct"] == pytest.approx(16.667, abs=0.01)


def test_delta_handles_empty_recent():
    out = delta([], _series([60.0] * 30), value_key="value")
    assert out == {"recent_avg": None, "prior_avg": 60.0, "abs": None, "pct": None}


def test_delta_handles_zero_baseline():
    """Zero baseline must not blow up the pct calc."""
    out = delta(_series([5.0]), _series([0.0, 0.0]), value_key="value")
    assert out["pct"] is None  # undefined when prior=0
    assert out["abs"] == 5.0


def test_anomaly_flag_fires_when_latest_below_baseline():
    # Baseline ~60, latest 45 → -25%, fires at default 15% threshold.
    flag = anomaly_flag(latest=45.0, baseline_avg=60.0)
    assert flag is not None
    assert flag["direction"] == "down"
    assert flag["pct"] == pytest.approx(-25.0, abs=0.01)


def test_anomaly_flag_fires_when_latest_above_baseline():
    flag = anomaly_flag(latest=80.0, baseline_avg=60.0)
    assert flag is not None
    assert flag["direction"] == "up"
    assert flag["pct"] == pytest.approx(33.333, abs=0.01)


def test_anomaly_flag_silent_when_within_threshold():
    assert anomaly_flag(latest=63.0, baseline_avg=60.0) is None


def test_anomaly_flag_silent_on_missing_data():
    assert anomaly_flag(latest=None, baseline_avg=60.0) is None
    assert anomaly_flag(latest=60.0, baseline_avg=None) is None
    assert anomaly_flag(latest=60.0, baseline_avg=0.0) is None


def test_anomaly_flag_custom_threshold():
    # 5% below baseline, default threshold 15% → no flag; 4% threshold → flag.
    assert anomaly_flag(latest=57.0, baseline_avg=60.0) is None
    flag = anomaly_flag(latest=57.0, baseline_avg=60.0, threshold_pct=4.0)
    assert flag is not None and flag["direction"] == "down"
