"""Findings pipeline — deterministic pre-flight over raw metrics.

Pure-ish: most helpers are plain functions over lists of {ts, value}
dicts. `build_findings` is the only IO-touching function, and it
delegates fetching to the existing repos.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

# Minimum points needed to fit a regression slope.
MIN_POINTS_FOR_SLOPE = 2
# Local hour at which the eating window is considered closed; calorie
# shortfalls vs target after this matter (mid-day pacing does not).
EATING_WINDOW_CLOSE_HOUR = 19


def _values(series: Sequence[dict[str, Any]], value_key: str) -> list[float]:
    """Extract non-None numeric values, preserving order."""
    out: list[float] = []
    for row in series:
        v = row.get(value_key)
        if v is None:
            continue
        out.append(float(v))
    return out


def trend(
    series: Sequence[dict[str, Any]], *, value_key: str,
) -> dict[str, Any]:
    """Summarize a time-series.

    `series` is oldest-first; callers pre-slice to the window of interest.
    `slope_per_day` is the simple linear-regression slope assuming one
    sample per day. None when too few points.
    """
    values = _values(series, value_key)
    if not values:
        return {"count": 0, "avg": None, "slope_per_day": None,
                "first": None, "last": None}
    n = len(values)
    avg = sum(values) / n
    if n < MIN_POINTS_FOR_SLOPE:
        slope = None
    else:
        # Simple linear regression over index 0..n-1.
        mean_x = (n - 1) / 2.0
        mean_y = avg
        num = sum((i - mean_x) * (v - mean_y) for i, v in enumerate(values))
        den = sum((i - mean_x) ** 2 for i in range(n))
        slope = num / den if den else None
    return {
        "count": n,
        "avg": round(avg, 3),
        "slope_per_day": round(slope, 3) if slope is not None else None,
        "first": values[0],
        "last": values[-1],
    }


def delta(
    recent: Sequence[dict[str, Any]],
    prior: Sequence[dict[str, Any]],
    *,
    value_key: str,
) -> dict[str, Any]:
    """Compare two windows' averages.

    `recent` and `prior` are oldest-first lists. Returns absolute and
    percentage delta of recent vs prior averages. `pct` is None when
    prior is 0 or empty.
    """
    r = _values(recent, value_key)
    p = _values(prior, value_key)
    r_avg = round(sum(r) / len(r), 3) if r else None
    p_avg = round(sum(p) / len(p), 3) if p else None
    if r_avg is None or p_avg is None:
        return {"recent_avg": r_avg, "prior_avg": p_avg, "abs": None, "pct": None}
    abs_delta = round(r_avg - p_avg, 3)
    pct = round((abs_delta / p_avg) * 100.0, 3) if p_avg != 0 else None
    return {"recent_avg": r_avg, "prior_avg": p_avg, "abs": abs_delta, "pct": pct}


def anomaly_flag(
    *,
    latest: float | None,
    baseline_avg: float | None,
    threshold_pct: float = 15.0,
) -> dict[str, Any] | None:
    """Return `{direction, pct}` when `latest` deviates from `baseline_avg`
    by more than `threshold_pct`; None otherwise.
    """
    if latest is None or baseline_avg is None or baseline_avg == 0:
        return None
    pct = ((latest - baseline_avg) / baseline_avg) * 100.0
    if abs(pct) < threshold_pct:
        return None
    return {
        "direction": "up" if pct > 0 else "down",
        "pct": round(pct, 3),
    }


@dataclass
class Findings:
    """Pre-digested context for the coach prompt.

    Structure: deterministic Python computes everything the prompt needs,
    so the model isn't asked to derive "is this on track?" from raw JSON.
    """
    snapshot: dict[str, Any] = field(default_factory=dict)
    food_totals: dict[str, Any] = field(default_factory=dict)
    targets: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    on_track: list[str] = field(default_factory=list)
    attention: list[str] = field(default_factory=list)
    local: dict[str, Any] = field(default_factory=dict)
    habits: list[dict[str, Any]] = field(default_factory=list)
    # Free-form notes the user maintains via /profile/day-note and
    # /profile/coach-note. Both are None when unset; the prompt renderer
    # omits the corresponding block entirely so an empty profile leaves
    # no trace in the prompt.
    day_note: str | None = None
    coach_note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def bucket_metrics(
    metrics: dict[str, dict[str, Any]],
    *,
    food_totals: dict[str, Any],
    targets: dict[str, Any],
    local_hour: int | None = None,
) -> tuple[list[str], list[str]]:
    """Split metrics + food/target signals into (on_track, attention).

    Rules:
    - A metric whose `anomaly` field is non-None lands in `attention`.
    - All other metrics land in `on_track`.
    - Food: calories under target by >25% lands in `attention` ONLY when
      the eating window is effectively closed (local_hour >= 19).
    """
    on_track: list[str] = []
    attention: list[str] = []
    for name, m in metrics.items():
        if m.get("anomaly"):
            attention.append(name)
        else:
            on_track.append(name)
    cal_target = targets.get("daily_calories")
    cal_actual = food_totals.get("calories")
    if (
        cal_target
        and cal_actual is not None
        and local_hour is not None
        and local_hour >= EATING_WINDOW_CLOSE_HOUR
        and cal_actual < cal_target * 0.75
    ):
        attention.append("calories")
    return on_track, attention


async def build_findings(
    metrics_repo: Any,
    food_repo: Any,
    *,
    day_start: datetime | None = None,
    day_end: datetime | None = None,
    targets: dict[str, Any] | None = None,
) -> Findings:
    """Deterministic pre-flight for the brief prompt.

    Returns a populated `Findings`. All field shapes match what
    `render_brief_prompt` (Task 7) expects to read.
    """
    # Imports inside the function to avoid a cycle with brief.py at module
    # load time — context.py is imported by brief.py.
    from app.services.coach.brief import (  # noqa: PLC0415
        gather_context,
        resolve_day_window,
        today_food_totals,
    )

    day_start, day_end = resolve_day_window(day_start, day_end)
    snapshot = await gather_context(
        metrics_repo, day_start=day_start, day_end=day_end, targets=targets,
    )
    food_totals = await today_food_totals(food_repo, day_start, day_end)

    now = datetime.now(UTC)
    # Add a small buffer to the window start to avoid sub-second boundary
    # misses when seeds land right on the exact cutoff.
    win7_start = now - timedelta(days=7, seconds=60)
    win7_end = now
    win30_start = now - timedelta(days=30, seconds=60)
    win30_end = now - timedelta(days=7)

    hrv_recent = await metrics_repo.range_hrv(win7_start, win7_end)
    hrv_prior = await metrics_repo.range_hrv(win30_start, win30_end)
    hrv_latest = (snapshot.get("hrv") or {}).get("rmssd_ms")
    hrv_t7 = trend(hrv_recent, value_key="rmssd_ms")
    hrv_t30 = trend(
        await metrics_repo.range_hrv(now - timedelta(days=30), now),
        value_key="rmssd_ms",
    )
    hrv_delta = delta(hrv_recent, hrv_prior, value_key="rmssd_ms")
    hrv_anom = anomaly_flag(latest=hrv_latest, baseline_avg=hrv_t30["avg"])

    weight_recent = await metrics_repo.range_weight(win7_start, win7_end)
    weight_prior = await metrics_repo.range_weight(win30_start, win30_end)
    weight_30 = await metrics_repo.range_weight(now - timedelta(days=30), now)
    weight_latest_lb = (snapshot.get("weight") or {}).get("lb")
    # snapshot.weight is in lb already — convert back for the kg-based series.
    weight_latest_kg = (
        weight_latest_lb / 2.2046226 if weight_latest_lb is not None else None
    )
    weight_t7 = trend(weight_recent, value_key="kg")
    weight_t30 = trend(weight_30, value_key="kg")
    weight_delta = delta(weight_recent, weight_prior, value_key="kg")
    weight_anom = anomaly_flag(
        latest=weight_latest_kg, baseline_avg=weight_t30["avg"],
    )

    metrics = {
        "hrv": {
            "latest": hrv_latest, "trend_7d": hrv_t7, "trend_30d": hrv_t30,
            "delta_7d_vs_30d": hrv_delta, "anomaly": hrv_anom,
        },
        "weight": {
            "latest_kg": weight_latest_kg,
            "latest_lb": weight_latest_lb,
            "trend_7d": weight_t7, "trend_30d": weight_t30,
            "delta_7d_vs_30d": weight_delta, "anomaly": weight_anom,
        },
        "sleep_score": {
            "latest": (snapshot.get("sleep") or {}).get("score"),
            "anomaly": None,
        },
        "steps_today": {
            "latest": snapshot.get("steps_today"),
            "anomaly": None,
        },
    }

    local_hour = snapshot.get("local_hour")
    on_track, attention = bucket_metrics(
        metrics,
        food_totals=food_totals,
        targets=snapshot.get("targets") or {},
        local_hour=local_hour,
    )

    import os  # noqa: PLC0415
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError  # noqa: PLC0415

    from app.services.coach.habits import compose_today  # noqa: PLC0415

    tz_name = os.environ.get("TZ") or "UTC"
    try:
        local_tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        local_tz = ZoneInfo("UTC")
    local_today_date = day_start.astimezone(local_tz).date()
    habits_today = await compose_today(metrics_repo.db, local_today_date, tz=local_tz)

    # User-maintained notes — None when unset / day-rolled (the helpers
    # apply the local-date dedupe themselves).
    from app.routers.profile import get_coach_note, get_day_note  # noqa: PLC0415
    day_note = await get_day_note(metrics_repo.db)
    coach_note = await get_coach_note(metrics_repo.db)

    return Findings(
        snapshot=snapshot,
        food_totals=food_totals,
        targets=snapshot.get("targets") or {},
        metrics=metrics,
        on_track=on_track,
        attention=attention,
        local={
            "now": snapshot.get("local_now"),
            "hour": local_hour,
            "time_of_day": snapshot.get("time_of_day"),
        },
        habits=habits_today,
        day_note=day_note,
        coach_note=coach_note,
    )
