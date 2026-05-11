"""Unit tests for the coach Findings pipeline.

Pure functions over plain dicts — no Mongo here. The `build_findings`
test (later) covers the integration over real repos.
"""
from datetime import UTC, datetime, timedelta
from datetime import timedelta as _td

import pytest

from app.models.metrics import HRV, Sleep, Weight
from app.services.coach.context import (
    Findings,
    anomaly_flag,
    bucket_metrics,
    build_findings,
    delta,
    trend,
)
from app.services.coach.habits import HabitConfig, create_habit
from app.services.food_repo import FoodRepo
from app.services.metrics_repo import MetricsRepo


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
    out = trend(series, value_key="value")
    assert out["count"] == 7
    assert out["avg"] == pytest.approx(66.0, abs=0.01)
    # Slope is "per day": rising 2 units/day across 7 points.
    assert out["slope_per_day"] == pytest.approx(2.0, abs=0.01)
    assert out["first"] == 60.0
    assert out["last"] == 72.0


def test_trend_handles_empty_series():
    out = trend([], value_key="value")
    assert out == {
        "count": 0, "avg": None, "slope_per_day": None,
        "first": None, "last": None,
    }


def test_trend_ignores_missing_values():
    series = _series([60.0, 0.0, 64.0])  # placeholder for missing
    series[1]["value"] = None
    out = trend(series, value_key="value")
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


def test_findings_dataclass_round_trips_to_dict():
    f = Findings(
        snapshot={"sleep": {"score": 80}},
        food_totals={"calories": 1500, "entries": 3, "food_logged_today": True},
        targets={"daily_calories": 2200, "daily_protein_g": 180,
                 "daily_water_oz": None, "step_goal_override": None},
        metrics={"hrv": {"latest": 33.0, "trend_7d": None, "trend_30d": None,
                          "delta_7d_vs_30d": None, "anomaly": None}},
        on_track=["sleep"],
        attention=["hrv"],
        local={"now": "07:30", "hour": 7, "time_of_day": "morning"},
    )
    d = f.to_dict()
    assert d["snapshot"]["sleep"]["score"] == 80
    assert d["on_track"] == ["sleep"]
    assert d["attention"] == ["hrv"]
    assert d["local"]["hour"] == 7


def test_bucket_metrics_routes_anomalies_to_attention():
    metrics = {
        "hrv": {"anomaly": {"direction": "down", "pct": -25.0}},
        "sleep_score": {"anomaly": None},
        "weight": {"anomaly": {"direction": "up", "pct": 3.0}},
    }
    on_track, attention = bucket_metrics(metrics, food_totals={}, targets={})
    assert "hrv" in attention
    assert "weight" in attention
    assert "sleep_score" in on_track


def test_bucket_metrics_flags_food_under_target_after_window_closes():
    """Calories meaningfully under target with the eating window closed
    (local_hour >= 19) is an attention item; same shortfall mid-day is not."""
    food_totals = {"calories": 1200.0, "food_logged_today": True}
    targets = {"daily_calories": 2200}
    # Mid-day — pacing is fine.
    _, attention = bucket_metrics(
        {}, food_totals=food_totals, targets=targets, local_hour=14,
    )
    assert "calories" not in attention
    # Evening — shortfall matters.
    _, attention = bucket_metrics(
        {}, food_totals=food_totals, targets=targets, local_hour=20,
    )
    assert "calories" in attention


def test_bucket_metrics_ignores_metrics_without_anomaly_field():
    """If a metric lacks the 'anomaly' key it's treated as on_track —
    safe default so a partial findings dict doesn't blow the bucketer up."""
    metrics = {"steps_today": {"value": 8000}}  # no 'anomaly' key
    on_track, attention = bucket_metrics(metrics, food_totals={}, targets={})
    assert "steps_today" in on_track
    assert attention == []


async def test_build_findings_returns_structured_object(mock_db):
    repo = MetricsRepo(mock_db)
    food_repo = FoodRepo(mock_db)
    now = datetime.now(UTC)
    # Seed HRV: 30 days at ~60 baseline, last 7 days dropping to ~40.
    for i in range(30, 0, -1):
        await repo.insert_hrv(HRV(
            ts=now - _td(days=i),
            rmssd_ms=40.0 if i <= 7 else 60.0,
            source="garmin", source_id=f"h:{i}",
        ))
    # Weight: stable around 108 kg for 30 days, latest 108.0.
    for i in range(30, 0, -1):
        await repo.insert_weight(Weight(
            ts=now - _td(days=i),
            kg=108.0,
            source="garmin", source_id=f"w:{i}",
        ))
    # Sleep: today's only.
    await repo.insert_sleep(Sleep(
        ts=now, duration_s=27000, deep_s=3600, rem_s=5400,
        light_s=16000, awake_s=2000, score=80,
        source="garmin", source_id="s:1",
    ))

    findings = await build_findings(repo, food_repo, targets=None)

    assert "hrv" in findings.metrics
    hrv = findings.metrics["hrv"]
    assert hrv["latest"] == 40.0
    assert hrv["trend_7d"]["count"] == 7
    assert hrv["trend_30d"]["count"] >= 28  # full window minus today edge
    # 7d avg ~40 vs prior-30d ~60 → down ~33% → anomaly fires.
    assert hrv["anomaly"] is not None
    assert hrv["anomaly"]["direction"] == "down"
    assert "hrv" in findings.attention

    # Weight is flat — no anomaly, on_track.
    assert findings.metrics["weight"]["anomaly"] is None
    assert "weight" in findings.on_track

    # Snapshot still present (back-compat with FE debug panel).
    assert findings.snapshot["sleep"]["score"] == 80
    assert "lb" in findings.snapshot["weight"]  # converted from kg

    # Local time block present.
    assert "hour" in findings.local
    assert "now" in findings.local


async def test_build_findings_includes_active_habits(mock_db):
    await create_habit(mock_db, HabitConfig(
        name="make the bed", kind="manual",
    ))
    repo = MetricsRepo(mock_db)
    food_repo = FoodRepo(mock_db)
    findings = await build_findings(repo, food_repo, targets=None)
    # New top-level field on Findings.to_dict() and dataclass.
    assert isinstance(findings.habits, list)
    names = [h["name"] for h in findings.habits]
    assert "make the bed" in names
    bed = next(h for h in findings.habits if h["name"] == "make the bed")
    assert bed["status"] == "unknown"  # not marked yet
