"""Findings pipeline — deterministic pre-flight over raw metrics.

Pure-ish: most helpers are plain functions over lists of {ts, value}
dicts. `build_findings` is the only IO-touching function, and it
delegates fetching to the existing repos.
"""
from __future__ import annotations

from collections.abc import Sequence
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


def delta(*args, **kwargs):  # placeholder — implemented in Task 3
    raise NotImplementedError


def anomaly_flag(*args, **kwargs):  # placeholder — implemented in Task 4
    raise NotImplementedError
