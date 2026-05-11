"""Findings pipeline — deterministic pre-flight over raw metrics.

Pure-ish: most helpers are plain functions over lists of {ts, value}
dicts. `build_findings` is the only IO-touching function, and it
delegates fetching to the existing repos.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any


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
    series: Sequence[dict[str, Any]], *, value_key: str, window_days: int,
) -> dict[str, Any]:
    """Summarize a time-series window.

    `series` is oldest-first. `slope_per_day` is the simple linear-regression
    slope assuming one sample per day. None when too few points.
    """
    del window_days  # reserved for future windowing inside the helper
    values = _values(series, value_key)
    if not values:
        return {"count": 0, "avg": None, "slope_per_day": None,
                "first": None, "last": None}
    n = len(values)
    avg = sum(values) / n
    if n < 2:
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
        and local_hour >= 19
        and cal_actual < cal_target * 0.75
    ):
        attention.append("calories")
    return on_track, attention
