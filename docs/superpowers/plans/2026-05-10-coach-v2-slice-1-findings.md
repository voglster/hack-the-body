# Coach v2 — Slice 1: Findings + Brief Path

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the coach's raw-snapshot context with a deterministic, pre-digested `Findings` object (trends, deltas, anomalies, on-track / attention buckets). The brief path uses Findings instead of dumping JSON at the model. No new collections, no UI changes, no chat, no tools.

**Architecture:** Move `services/coach.py` into a package `services/coach/`. Add `coach/context.py` (helpers + `build_findings`) and `coach/brief.py` (renamed `generate_insight` → `generate_brief` internally, plus a re-export shim so existing callers don't break). Trim `SYSTEM_PROMPT` once Findings carries baselines structurally.

**Tech Stack:** Python 3.12, FastAPI, Motor (async PyMongo), pytest-asyncio. Tests live in `services/api/tests/`.

**Spec:** `docs/superpowers/specs/2026-05-10-coach-v2-design.md`

---

## File Structure

**Created**
- `services/api/app/services/coach/__init__.py` — re-exports `generate_insight`, `recent_insights`, `save_insight`, `Insight`, `SYSTEM_PROMPT`, `gather_context`, `today_food_totals`, `resolve_day_window` so the router and scheduler don't need to change.
- `services/api/app/services/coach/context.py` — `Findings` dataclass, trend/delta/anomaly helpers, `build_findings()`.
- `services/api/app/services/coach/brief.py` — `SYSTEM_PROMPT`, `Insight`, `gather_context`, `today_food_totals`, `resolve_day_window`, `recent_insights`, `save_insight`, `_format_prompt`, `generate_insight`. (The bulk of today's `coach.py`.)
- `services/api/tests/test_findings.py` — unit tests for trend/delta/anomaly helpers and `build_findings`.

**Modified**
- `services/api/app/services/coach/brief.py` — once Findings is wired in, `_format_prompt` becomes `render_brief_prompt(findings, food_totals, history)`; `generate_insight` builds findings and renders from them.
- `services/api/tests/test_coach.py` — a few prompt-content assertions tighten or relax as the SYSTEM_PROMPT is trimmed and Findings replaces raw JSON.

**Deleted**
- `services/api/app/services/coach.py` — replaced by the package. (Git move; no behavior change at the move step.)

**Untouched (by design)**
- `services/api/app/routers/coach.py`
- `services/api/app/services/scheduler.py`
- Mongo collections / migrations
- Frontend

---

## Conventions for this plan

- Run tests from `services/api/`:
  ```
  cd services/api && .venv/bin/pytest -v
  ```
- Commit after each green task. Conventional Commit messages.
- "FAIL" expectations specify the import/assertion error string when known.
- Existing test file: `services/api/tests/test_coach.py`. New file: `services/api/tests/test_findings.py`.

---

### Task 1: Move `coach.py` into a `coach/` package (no behavior change)

**Files:**
- Create: `services/api/app/services/coach/__init__.py`
- Create: `services/api/app/services/coach/brief.py`
- Delete: `services/api/app/services/coach.py`

- [ ] **Step 1: Confirm current tests pass**

```
cd services/api && .venv/bin/pytest tests/test_coach.py -v
```

Expected: all tests in `test_coach.py` PASS. (If not, stop and fix before refactoring.)

- [ ] **Step 2: Create the package and move file contents**

```bash
mkdir -p services/api/app/services/coach
git mv services/api/app/services/coach.py services/api/app/services/coach/brief.py
```

- [ ] **Step 3: Write `coach/__init__.py` re-exporting everything callers use**

Create `services/api/app/services/coach/__init__.py` with:

```python
"""Coach package — brief generation, (future) chat agent loop, tools, memory.

For now this is a thin re-export layer over `brief.py` so existing callers
(router, scheduler, tests) keep working while the package fills out.
"""
from app.services.coach.brief import (  # noqa: F401
    RECENT_LIMIT,
    SYSTEM_PROMPT,
    USER_PROFILE,
    Insight,
    gather_context,
    generate_insight,
    recent_insights,
    resolve_day_window,
    save_insight,
    today_food_totals,
)
```

- [ ] **Step 4: Run the full test suite to verify no regression**

```
cd services/api && .venv/bin/pytest -v
```

Expected: same pass count as Step 1. No new failures.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/coach/
git commit -m "refactor(coach): move coach.py into coach/ package"
```

---

### Task 2: Add a pure `trend()` helper with unit tests

**Files:**
- Create: `services/api/app/services/coach/context.py`
- Create: `services/api/tests/test_findings.py`

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_findings.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd services/api && .venv/bin/pytest tests/test_findings.py -v
```

Expected: FAIL with `ImportError` (module `app.services.coach.context` does not exist yet).

- [ ] **Step 3: Implement `trend` in `coach/context.py`**

Create `services/api/app/services/coach/context.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd services/api && .venv/bin/pytest tests/test_findings.py -v
```

Expected: 3 PASS in `test_findings.py`. Other test files unaffected.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/coach/context.py services/api/tests/test_findings.py
git commit -m "feat(coach): add trend() helper for windowed metric summaries"
```

---

### Task 3: Add `delta()` helper (week-over-week / window-vs-window)

**Files:**
- Modify: `services/api/app/services/coach/context.py`
- Modify: `services/api/tests/test_findings.py`

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_findings.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd services/api && .venv/bin/pytest tests/test_findings.py -v
```

Expected: 3 FAIL with `NotImplementedError` from the placeholder.

- [ ] **Step 3: Implement `delta`**

Replace the `delta` placeholder in `services/api/app/services/coach/context.py` with:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd services/api && .venv/bin/pytest tests/test_findings.py -v
```

Expected: 6 PASS total in `test_findings.py`.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/coach/context.py services/api/tests/test_findings.py
git commit -m "feat(coach): add delta() helper for window-vs-window comparison"
```

---

### Task 4: Add `anomaly_flag()` helper

**Files:**
- Modify: `services/api/app/services/coach/context.py`
- Modify: `services/api/tests/test_findings.py`

Decision: a metric is "anomalous" when the latest value is more than `threshold_pct` away from the prior-window average. Default threshold 15%.

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_findings.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd services/api && .venv/bin/pytest tests/test_findings.py -v
```

Expected: 5 FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement `anomaly_flag`**

Replace the `anomaly_flag` placeholder in `services/api/app/services/coach/context.py` with:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd services/api && .venv/bin/pytest tests/test_findings.py -v
```

Expected: 11 PASS total in `test_findings.py`.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/coach/context.py services/api/tests/test_findings.py
git commit -m "feat(coach): add anomaly_flag() helper for baseline deviations"
```

---

### Task 5: Define the `Findings` dataclass and `bucket_metrics()`

**Files:**
- Modify: `services/api/app/services/coach/context.py`
- Modify: `services/api/tests/test_findings.py`

The bucketer takes a partial findings dict (per-metric trend/delta/anomaly) and a `targets` dict and returns `(on_track, attention)` lists. It's the structured replacement for "model, please decide what's worth mentioning."

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_findings.py`:

```python
from app.services.coach.context import Findings, bucket_metrics


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
    on_track, attention = bucket_metrics(
        {}, food_totals=food_totals, targets=targets, local_hour=14,
    )
    assert "calories" not in attention
    # Evening — shortfall matters.
    on_track, attention = bucket_metrics(
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
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd services/api && .venv/bin/pytest tests/test_findings.py -v
```

Expected: 4 FAIL with `ImportError` on `Findings`/`bucket_metrics`.

- [ ] **Step 3: Implement `Findings` and `bucket_metrics`**

Append to `services/api/app/services/coach/context.py`:

```python
from dataclasses import asdict, dataclass, field


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
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd services/api && .venv/bin/pytest tests/test_findings.py -v
```

Expected: 15 PASS total in `test_findings.py`.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/coach/context.py services/api/tests/test_findings.py
git commit -m "feat(coach): add Findings dataclass and metric bucketer"
```

---

### Task 6: Implement `build_findings()` against the live repos

**Files:**
- Modify: `services/api/app/services/coach/context.py`
- Modify: `services/api/tests/test_findings.py`

`build_findings` fetches:
- Latest sleep / HRV / weight / daily summary (today's snapshot — same as current `gather_context`).
- 7-day and 30-day windows for HRV (`rmssd_ms`), weight (`kg`), sleep score (from daily summary `sleep_score` or sleep doc `score`), steps (sum from daily summaries).
- Computes per-metric `{latest, trend_7d, trend_30d, delta_7d_vs_30d, anomaly}`.
- Calls `bucket_metrics` to fill on_track / attention.
- Includes the local-time block from current `gather_context`.

For Slice 1 we'll cover HRV and weight as the two trend-bearing metrics; sleep score and steps stay in the snapshot but get added to the metrics dict with `anomaly: None` (they land on_track by default). Later slices can add their own trends.

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_findings.py`:

```python
from datetime import timedelta as _td

from app.models.metrics import HRV, Sleep, Weight
from app.services.coach.context import build_findings
from app.services.metrics_repo import MetricsRepo
from app.services.food_repo import FoodRepo


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
```

- [ ] **Step 2: Run test to verify it fails**

```
cd services/api && .venv/bin/pytest tests/test_findings.py::test_build_findings_returns_structured_object -v
```

Expected: FAIL with `ImportError` on `build_findings`.

- [ ] **Step 3: Implement `build_findings`**

Append to `services/api/app/services/coach/context.py`:

```python
from datetime import UTC, datetime, timedelta


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
    from app.services.coach.brief import (
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
    win7_start, win7_end = now - timedelta(days=7), now
    win30_start, win30_end = now - timedelta(days=30), now - timedelta(days=7)

    hrv_recent = await metrics_repo.range_hrv(win7_start, win7_end)
    hrv_prior = await metrics_repo.range_hrv(win30_start, win30_end)
    hrv_latest = (snapshot.get("hrv") or {}).get("rmssd_ms")
    hrv_t7 = trend(hrv_recent, value_key="rmssd_ms", window_days=7)
    hrv_t30 = trend(
        await metrics_repo.range_hrv(now - timedelta(days=30), now),
        value_key="rmssd_ms", window_days=30,
    )
    hrv_delta = delta(hrv_recent, hrv_prior, value_key="rmssd_ms")
    hrv_anom = anomaly_flag(latest=hrv_latest, baseline_avg=hrv_t30["avg"])

    weight_recent = await metrics_repo.range_weight(win7_start, win7_end)
    weight_prior = await metrics_repo.range_weight(win30_start, win30_end)
    weight_30 = await metrics_repo.range_weight(now - timedelta(days=30), now)
    weight_latest_kg = (snapshot.get("weight") or {}).get("lb")
    # snapshot.weight is in lb already — convert back for the kg-based series.
    weight_latest_kg = (
        weight_latest_kg / 2.2046226 if weight_latest_kg is not None else None
    )
    weight_t7 = trend(weight_recent, value_key="kg", window_days=7)
    weight_t30 = trend(weight_30, value_key="kg", window_days=30)
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
            "latest_lb": (snapshot.get("weight") or {}).get("lb"),
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
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd services/api && .venv/bin/pytest tests/test_findings.py -v
```

Expected: 16 PASS total in `test_findings.py`.

- [ ] **Step 5: Run the full suite to catch any indirect breakage**

```
cd services/api && .venv/bin/pytest -v
```

Expected: same baseline pass count plus the new tests.

- [ ] **Step 6: Commit**

```bash
git add services/api/app/services/coach/context.py services/api/tests/test_findings.py
git commit -m "feat(coach): implement build_findings() over live repos"
```

---

### Task 7: Render brief prompt from `Findings` (replace raw JSON dump)

**Files:**
- Modify: `services/api/app/services/coach/brief.py`
- Modify: `services/api/tests/test_coach.py`

`generate_insight` keeps its public signature (`trigger`, `day_start`, `day_end`, `targets`). Internally it now builds a `Findings` and calls a new `render_brief_prompt(findings, history)`. The rendered prompt:

1. Includes the SYSTEM_PROMPT + USER_PROFILE block (unchanged for now).
2. Replaces the `Latest data: <json>` dump with a structured block:
   - `Snapshot:` — same fields as today's `context` (sleep, HRV, weight, daily summary, steps_today, local times, targets).
   - `Metrics:` — per-metric trend_7d/trend_30d/delta/anomaly summaries.
   - `On track:` — comma-list of `findings.on_track`.
   - `Attention:` — comma-list of `findings.attention` (or "none").
3. Today's food totals block unchanged.
4. Recent coach messages block unchanged.

We will continue to persist the raw `context` field on saved insights (it now equals `findings.to_dict()`) so the FE debug panel and feedback tools keep working.

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_coach.py`:

```python
async def test_insight_prompt_includes_findings_attention_block(
    client, mock_db, fake_ollama_response,
):
    """The new pre-digested prompt has explicit `Attention:` / `On track:`
    blocks computed by Python so the model doesn't have to derive them."""
    await _seed(mock_db)

    captured: dict = {}
    class _MockResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return fake_ollama_response
    async def _fake_post(_self, _url, json=None):
        captured["payload"] = json
        return _MockResp()

    with patch.object(httpx.AsyncClient, "post", _fake_post):
        r = await client.get("/coach/insight", headers=HEADERS)

    assert r.status_code == 200
    prompt = captured["payload"]["prompt"]
    assert "Attention:" in prompt
    assert "On track:" in prompt
    # The saved insight's `context` field carries the full findings dict.
    body = r.json()
    assert "on_track" in body["context"]
    assert "attention" in body["context"]
    assert "metrics" in body["context"]
```

- [ ] **Step 2: Run test to verify it fails**

```
cd services/api && .venv/bin/pytest tests/test_coach.py::test_insight_prompt_includes_findings_attention_block -v
```

Expected: FAIL — `"Attention:" in prompt` is False.

- [ ] **Step 3: Implement `render_brief_prompt` and rewire `generate_insight`**

In `services/api/app/services/coach/brief.py`, **add** a new function and **modify** `generate_insight`:

Add near the bottom of the file (above `generate_insight`):

```python
def render_brief_prompt(
    findings: "Findings",
    history: list[dict[str, Any]],
) -> str:
    parts = [SYSTEM_PROMPT, "", f"Client: {USER_PROFILE}", ""]
    parts.append("Snapshot:")
    parts.append(json.dumps(findings.snapshot, indent=2, default=str))
    parts.append("")
    parts.append("Metrics (trends + anomalies):")
    parts.append(json.dumps(findings.metrics, indent=2, default=str))
    parts.append("")
    parts.append(f"On track: {', '.join(findings.on_track) or 'none'}")
    parts.append(f"Attention: {', '.join(findings.attention) or 'none'}")
    parts.append("")
    if findings.food_totals:
        parts.append("Today's food totals:")
        parts.append(json.dumps(findings.food_totals, indent=2, default=str))
    if history:
        parts.append("Recent coach messages (oldest first):")
        for h in reversed(history):
            ts = h.get("generated_at")
            ts_s = (
                ts.isoformat(timespec="minutes")
                if isinstance(ts, datetime) else str(ts)
            )
            parts.append(f"[{h.get('trigger', 'manual')} @ {ts_s}] {h.get('text', '')}")
    return "\n".join(parts)
```

Add this import at the top of `brief.py` if not already present:

```python
from app.services.coach.context import Findings, build_findings
```

Replace the body of `generate_insight` with:

```python
async def generate_insight(
    settings: Settings,
    db: AsyncDatabase,
    *,
    trigger: str = "manual",
    day_start: datetime | None = None,
    day_end: datetime | None = None,
    targets: dict[str, Any] | None = None,
) -> Insight:
    repo = MetricsRepo(db)
    food_repo = FoodRepo(db)
    day_start, day_end = resolve_day_window(day_start, day_end)
    findings = await build_findings(
        repo, food_repo,
        day_start=day_start, day_end=day_end, targets=targets,
    )
    history = await recent_insights(db, since=day_start)
    prompt = render_brief_prompt(findings, history)
    payload = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.4, "num_predict": 400},
    }
    async with httpx.AsyncClient(timeout=settings.coach_timeout_s) as c:
        r = await c.post(f"{settings.ollama_url}/api/generate", json=payload)
        r.raise_for_status()
        data = r.json()
    insight = Insight(
        text=(data.get("response") or "").strip(),
        model=settings.ollama_model,
        eval_ms=int(data.get("eval_duration", 0)) // 1_000_000,
        total_ms=int(data.get("total_duration", 0)) // 1_000_000,
        generated_at=datetime.now(UTC),
        context=findings.to_dict(),
        trigger=trigger,
        food_totals=findings.food_totals,
        history_snapshot=history,
        prompt=prompt,
        system_prompt=SYSTEM_PROMPT,
    )
    insight.id = await save_insight(db, insight)
    return insight
```

- [ ] **Step 4: Run the focused new test**

```
cd services/api && .venv/bin/pytest tests/test_coach.py::test_insight_prompt_includes_findings_attention_block -v
```

Expected: PASS.

- [ ] **Step 5: Run the full coach test file and fix regressions**

```
cd services/api && .venv/bin/pytest tests/test_coach.py -v
```

Expected: most tests still PASS. Some assertions that scan the *raw* JSON dump may fail because the prompt now has a `Snapshot:` block instead of a `Latest data:` block. Specifically, expect these to need updates:

- `test_insight_carries_water_total_separate_from_food` — asserts `'"water_oz": 32.0' in prompt`. The food_totals block still emits this exact key, so this should still pass.
- `test_insight_signals_no_food_logged_yet` — asserts `'"food_logged_today": false' in prompt` and `'"entries": 0' in prompt`. Both still emitted in the food_totals block; should still pass.
- `test_insight_includes_targets_in_prompt` — asserts `'"targets":' in prompt`. The targets now live inside `Snapshot:` JSON; the substring `"targets":` should still appear because `findings.snapshot` includes the `targets` key from `gather_context`. Should still pass.
- `test_insight_uses_local_day_window_for_food_and_history` — asserts `"local_now" in body["context"]`. `findings.to_dict()` carries `local.now` not `local_now`. **This will fail** — fix in the next step.

- [ ] **Step 6: Fix tests that asserted the old `context` shape**

In `services/api/tests/test_coach.py`, update `test_insight_uses_local_day_window_for_food_and_history`:

Replace:

```python
    body = r.json()
    assert "local_now" in body["context"]
    assert "local_hour" in body["context"]
    assert "time_of_day" in body["context"]
```

with:

```python
    body = r.json()
    # Findings nests local-time fields under `local`.
    assert "local" in body["context"]
    assert "now" in body["context"]["local"]
    assert "hour" in body["context"]["local"]
    assert "time_of_day" in body["context"]["local"]
```

Update `test_insight_returns_text_and_metadata`:

Replace:

```python
    assert body["context"]["sleep"]["duration_s"] == 27000
    assert body["context"]["hrv"]["rmssd_ms"] == 33.0
```

with:

```python
    assert body["context"]["snapshot"]["sleep"]["duration_s"] == 27000
    assert body["context"]["snapshot"]["hrv"]["rmssd_ms"] == 33.0
```

- [ ] **Step 7: Run the full suite**

```
cd services/api && .venv/bin/pytest -v
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add services/api/app/services/coach/brief.py services/api/tests/test_coach.py
git commit -m "feat(coach): render brief prompt from Findings (on_track/attention blocks)"
```

---

### Task 8: Trim `SYSTEM_PROMPT` (drop rules Findings makes redundant)

**Files:**
- Modify: `services/api/app/services/coach/brief.py`
- Modify: `services/api/tests/test_coach.py`

Per the spec's "Prompt cleanup" section:
- **Drop:** "don't invent baselines / TDEE" — Findings carries baselines structurally.
- **Drop:** "trust current snapshot over older messages" — Findings is authoritative; history is conversational.
- **Reframe:** the metric roll-call rule around `Attention` / `On track` blocks the model now sees.

Keep: food window, units, time-of-day, on-track close phrasing, clinical-alarmism ban, no-scolding rule.

Aim: under 30 lines (currently ~70).

- [ ] **Step 1: Write the failing test for the reframed roll-call rule**

In `services/api/tests/test_coach.py`, replace `test_system_prompt_forbids_metric_regurgitation` with:

```python
async def test_system_prompt_directs_model_to_attention_block():
    """With Findings carrying explicit On track / Attention lists, the
    prompt rule shifts from 'don't roll-call' to 'speak to Attention'."""
    lowered = SYSTEM_PROMPT.lower()
    assert "attention" in lowered
    assert "on track" in lowered or "on-track" in lowered
    # Positive instruction: only address the named attention items.
    assert "only address" in lowered or "name only attention" in lowered \
        or "address only" in lowered
```

- [ ] **Step 2: Run it to confirm it fails**

```
cd services/api && .venv/bin/pytest tests/test_coach.py::test_system_prompt_directs_model_to_attention_block -v
```

Expected: FAIL (current SYSTEM_PROMPT doesn't mention `Attention` / `On track`).

- [ ] **Step 3: Rewrite `SYSTEM_PROMPT` in `brief.py`**

Replace the existing `SYSTEM_PROMPT = (...)` block in `services/api/app/services/coach/brief.py` with:

```python
SYSTEM_PROMPT = (
    "You are a no-nonsense health coach speaking directly to your client. "
    "Use short sentences. Skip pleasantries. "
    "IMPORTANT — what to address: you are given explicit `On track:` and "
    "`Attention:` lists. Address only items in `Attention`, with the number "
    "from `Metrics` and one concrete action for the next 4 hours. If "
    "`Attention` is `none`, skip metrics entirely and close with ONE short, "
    "varied, upbeat line (e.g. 'Solid start — keep it rolling.' / 'Dialed "
    "in. Keep going.' / 'Green across the board.' / 'Nothing to fix — keep "
    "stacking the day.'). Never emit the exact same closer twice in a row "
    "given recent_coach_messages. Do not invent action items when "
    "`Attention` is empty. Keep total reply under 120 words; aim for under "
    "40 when on track. "
    "IMPORTANT — units: weight is reported as `weight.lb` (pounds). Always "
    "report weight in lbs. Never invent a kg value or convert. "
    "IMPORTANT — food: read `food_totals`. If `food_logged_today` is true "
    "OR `entries` > 0, food HAS been logged today — do NOT ask 'what did "
    "you eat' and do NOT say 'zero food logged'. When `food_logged_today` "
    "is false AND `entries` is 0, note neutrally that nothing is logged "
    "yet; never accuse the client of fasting or missing meals. "
    "IMPORTANT — eating window: the client follows 16/8 intermittent "
    "fasting with an eating window of roughly 11:00-19:00 local. When "
    "`local.hour` < 11, the client is intentionally fasting — do NOT "
    "mention food, protein, or 'log your meals'. When `local.hour` >= 19, "
    "the eating window is closing; only mention food if a target is "
    "meaningfully short. "
    "IMPORTANT — time: use `local.now` (their wall clock) for any "
    "time-of-day reasoning, never UTC. `local.hour` is the hour 0-23. "
    "IMPORTANT — tone: report numbers, do not dramatize them. NEVER use "
    "clinical or alarmist terms like 'catabolic', 'starving', 'metabolic "
    "collapse', 'crash', 'in danger'. The client is a healthy adult; a "
    "1500-calorie afternoon is not a crisis. NEVER scold, lecture, or "
    "reference 'warnings' you previously gave; do not use phrases like "
    "'you ignored', 'as I told you', 'you didn't listen'. Each reply "
    "stands alone. Treat the user as an adult collaborator."
)
```

- [ ] **Step 4: Update the test for `local_hour` reference**

The current `test_insight_signals_no_food_logged_yet` asserts the prompt contains the strings `"food_logged_today"` and `"food_totals.entries"`. The new SYSTEM_PROMPT keeps `food_logged_today` but not the literal `food_totals.entries`. Update that test in `services/api/tests/test_coach.py`:

Replace:

```python
    assert "food_logged_today" in prompt
    assert "food_totals.entries" in prompt
```

with:

```python
    assert "food_logged_today" in prompt
    assert "entries" in prompt
```

- [ ] **Step 5: Run the full coach test file**

```
cd services/api && .venv/bin/pytest tests/test_coach.py -v
```

Expected: all PASS, including:
- `test_system_prompt_directs_model_to_attention_block` (new)
- `test_system_prompt_allows_action_optional`
- `test_system_prompt_requires_weight_in_lbs`
- `test_system_prompt_requires_varied_positive_close`
- `test_system_prompt_forbids_clinical_alarmism`

If any of those fail, your trimmed SYSTEM_PROMPT dropped a phrase a test pins. Either restore the phrase or — if the test is genuinely obsolete — discuss before deleting.

- [ ] **Step 6: Verify the prompt is materially shorter**

```
cd services/api && .venv/bin/python -c "from app.services.coach.brief import SYSTEM_PROMPT; print(len(SYSTEM_PROMPT.split()))"
```

Expected: under 350 words (current is ~480). Not a hard fail; informational.

- [ ] **Step 7: Run the full suite**

```
cd services/api && .venv/bin/pytest -v
```

Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add services/api/app/services/coach/brief.py services/api/tests/test_coach.py
git commit -m "feat(coach): trim SYSTEM_PROMPT — Findings replaces baseline/snapshot rules"
```

---

### Task 9: Update the coach-debugging playbook to point at the new module paths

**Files:**
- Modify: `docs/coach-debugging.md`

- [ ] **Step 1: Find the references to the old `coach.py` path**

```bash
grep -n "services/coach.py\|services\\.coach\b\|coach.py::" docs/coach-debugging.md
```

- [ ] **Step 2: Replace with the new package paths**

In `docs/coach-debugging.md`, replace every `services/api/app/services/coach.py::SYSTEM_PROMPT` with `services/api/app/services/coach/brief.py::SYSTEM_PROMPT`, and any reference to "`coach.py`" with "`coach/brief.py`".

Add a short paragraph in the "Architecture notes" section noting that v2 introduced `coach/context.py::build_findings` which produces the pre-digested `Findings` the brief is now rendered from — and that the saved `context` field on each insight is now `Findings.to_dict()`, not the raw snapshot.

- [ ] **Step 3: Commit**

```bash
git add docs/coach-debugging.md
git commit -m "docs(coach): point debugging playbook at coach/ package paths"
```

---

### Task 10: Final verification

- [ ] **Step 1: Run the full test suite**

```
cd services/api && .venv/bin/pytest -v
```

Expected: all PASS, including the new findings tests and updated coach tests.

- [ ] **Step 2: Lint and typecheck**

```
cd services/api && .venv/bin/ruff check app tests && .venv/bin/mypy app
```

Expected: clean (or pre-existing warnings only — match the baseline).

- [ ] **Step 3: Sanity-check the brief end-to-end against a local LLM (optional but recommended)**

Start the API, hit `GET /coach/insight` once with your real `X-API-Key`, and read the response. Confirm:
- `text` looks like a coach reply, not garbage.
- `context.on_track` and `context.attention` are populated.
- `context.metrics.hrv` has `trend_7d`, `trend_30d`, `delta_7d_vs_30d`, `anomaly`.

If the model output regresses noticeably from current behavior, file what you saw and consider whether the SYSTEM_PROMPT cuts went too far before opening Slice 2.

- [ ] **Step 4: Push**

```bash
git push origin master
```

Watchtower picks up the rebuilt image on `hd` (~60s) and the next scheduled brief uses the new pipeline.

---

## Self-Review

**Spec coverage**

Slice 1 in the spec covers: "Replace `gather_context` with `build_findings`; brief uses the new pre-digested context. No tools yet, no chat."

- `build_findings` — Tasks 2-6.
- Brief uses pre-digested context — Task 7.
- Prompt cleanup that the spec calls out under "Slice 1 should already make the brief better" — Task 8.
- No new collections, no chat, no tools — confirmed (none added).
- Migration / rollout: Slice 1 is API-compatible (`/coach/insight` returns same JSON shape, with `context` now being the Findings dict). Feature flag `COACH_V2_ENABLED` is not needed for this slice — the new pipeline directly replaces the old one. The flag mechanism is set up in Slice 2 when the chat surface lands; existing call sites continue to work without one. This is a conscious deviation from the spec's blanket "behind a feature flag" rollout: Slice 1 has no UI change and is a pure backend improvement.

**Placeholder scan**

- No "TBD" / "TODO" in the plan.
- Every code step has the actual code.
- Every command has expected output.

**Type consistency**

- `Findings` defined in Task 5; consumed in Tasks 6 (build) and 7 (render). Field names match (`snapshot`, `food_totals`, `targets`, `metrics`, `on_track`, `attention`, `local`).
- `build_findings(metrics_repo, food_repo, *, day_start, day_end, targets)` signature consistent between Task 6 and Task 7's `generate_insight`.
- `bucket_metrics(metrics, *, food_totals, targets, local_hour)` consistent between Task 5 and Task 6.
- `anomaly_flag(*, latest, baseline_avg, threshold_pct)` consistent.
