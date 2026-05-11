# Coach v2 — Slice 3: Habits Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** First-class daily habits — auto-tracked (bed-by-10, vitamins), manually toggled (made-the-bed, brush-teeth), or just-named-nudges. Habit status feeds into `Findings` so the brief/chat knows what's done. Coach can call `habit_status` and `mark_habit_done` tools.

**Architecture:** Two new Mongo collections (`habits` config + `habit_status` daily rows). Resolvers (in code, keyed by `resolver` name) turn data we already collect into status for `auto` habits. Manual habits are user-toggled; `none` habits are just listed. A new card on the dashboard's "More" tab provides view + toggle + add. Tool registry gains `habit_status` and `mark_habit_done`.

**Tech Stack:** Python 3.12, FastAPI, Motor. React 19, TanStack Query, Tailwind.

**Spec:** `docs/superpowers/specs/2026-05-10-coach-v2-design.md` (Rollout → Slice 3).

**Slices already shipped:** 1 (Findings) at `839a01d`. 2 (Threads/Chat/Tools) at `1b75c63`.

---

## File Structure

**Created (backend)**
- `services/api/app/services/coach/habits.py` — habits + habit_status repos, resolver registry, today-status compose function.
- `services/api/app/routers/habits.py` — REST API for habits config + status.
- `services/api/tests/test_habits.py` — repo + resolver unit tests.
- `services/api/tests/test_habits_router.py` — endpoint integration tests.

**Modified (backend)**
- `services/api/app/main.py` — mount the new habits router.
- `services/api/app/services/coach/context.py` — `build_findings` includes `habit_status_today`.
- `services/api/app/services/coach/tools.py` — register `habit_status` and `mark_habit_done` tools.
- `services/api/app/services/coach/__init__.py` — re-export habits helpers.
- `services/api/tests/test_findings.py` — `build_findings` now carries habit statuses.
- `services/api/tests/test_coach_tools.py` — new tool tests.

**Created (frontend)**
- `services/web/src/components/HabitsCard.tsx` — view + toggle + add habit, lives on More tab.
- `services/web/src/components/HabitsCard.test.tsx` — minimal render test.

**Modified (frontend)**
- `services/web/src/api/types.ts` — `Habit`, `HabitStatus`, `HabitStatusToday`.
- `services/web/src/api/client.ts` — `habitsList`, `habitsToday`, `habitCreate`, `habitMarkStatus`.
- `services/web/src/pages/Dashboard.tsx` — render `<HabitsCard />` on the More tab between TargetsCard and NotificationsSettings.

**Untouched (by design)**
- `habit_status.schedule` (`days_per_week`, `time_window`) — field reserved but not honored this slice; all habits are daily.
- `mark_habit_skipped` / `mark_habit_missed` — not exposed as tools this slice; manual API call only.
- `bed_by_10` cutoff configurable per habit — hard-coded to 22:00 local for now.

---

## Conventions for this plan

Run backend tests from `services/api/`:
```
cd services/api && .venv/bin/pytest -q
```
Run FE tests from `services/web/`:
```
cd services/web && npm test -- --run
```
Lint:
```
cd services/api && .venv/bin/ruff check app tests
```
Slice-2 ended at HEAD `1b75c63` with 232 backend tests + 25 FE tests + 1 baseline lint error. Commit after each green task; **DO NOT push until Task 13.**

---

### Task 1: Habits config + status repos (storage layer)

**Files:**
- Create: `services/api/app/services/coach/habits.py`
- Create: `services/api/tests/test_habits.py`

- [ ] **Step 1: Write the failing tests**

Create `services/api/tests/test_habits.py`:

```python
"""Habits repos — config and daily status."""
from datetime import UTC, date, datetime

import pytest

from app.services.coach.habits import (
    HabitConfig,
    create_habit,
    get_active_habits,
    get_habit_by_name,
    list_habits,
    mark_status,
    status_for_day,
    update_habit,
)


async def test_create_and_list_habits(mock_db):
    h1 = await create_habit(mock_db, HabitConfig(
        name="bed by 10", kind="auto", resolver="bed_by_10",
    ))
    h2 = await create_habit(mock_db, HabitConfig(
        name="make the bed", kind="manual",
    ))
    rows = await list_habits(mock_db)
    names = sorted(r["name"] for r in rows)
    assert names == ["bed by 10", "make the bed"]
    # Each row has expected fields:
    assert all("active" in r and "kind" in r for r in rows)
    assert h1 != h2


async def test_get_active_habits_filters_inactive(mock_db):
    h = await create_habit(mock_db, HabitConfig(name="x", kind="manual"))
    await update_habit(mock_db, h, {"active": False})
    rows = await get_active_habits(mock_db)
    assert all(r["active"] for r in rows)
    assert all(r["name"] != "x" for r in rows)


async def test_get_habit_by_name(mock_db):
    await create_habit(mock_db, HabitConfig(name="brush teeth", kind="manual"))
    row = await get_habit_by_name(mock_db, "brush teeth")
    assert row is not None and row["name"] == "brush teeth"
    assert await get_habit_by_name(mock_db, "nope") is None


async def test_mark_status_upserts_for_day(mock_db):
    h = await create_habit(mock_db, HabitConfig(name="brush teeth", kind="manual"))
    today = date(2026, 5, 10)
    await mark_status(mock_db, h, today, status="done", source="manual")
    s = await status_for_day(mock_db, h, today)
    assert s["status"] == "done"
    assert s["source"] == "manual"

    # Re-marking the same day updates rather than duplicates.
    await mark_status(mock_db, h, today, status="skipped", source="coach")
    s = await status_for_day(mock_db, h, today)
    assert s["status"] == "skipped"
    assert s["source"] == "coach"
    count = await mock_db["habit_status"].count_documents({"habit_id": h, "local_date": today.isoformat()})
    assert count == 1


async def test_status_for_day_returns_none_when_unset(mock_db):
    h = await create_habit(mock_db, HabitConfig(name="x", kind="manual"))
    assert await status_for_day(mock_db, h, date(2026, 5, 10)) is None
```

- [ ] **Step 2: Run tests to verify failure**

```
cd services/api && .venv/bin/pytest tests/test_habits.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the repos**

Create `services/api/app/services/coach/habits.py`:

```python
"""Habits — config + daily status + auto resolvers.

Config rows live in `habits`; daily status in `habit_status` (one row per
habit per local date). `auto` habits derive their status from existing
data (sleep, vitamins, ...) via a named resolver. `manual` habits are
toggled by the user. `none` habits are just named nudges — no status.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any, Literal

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase

HabitKind = Literal["auto", "manual", "none"]
HabitStatusValue = Literal["done", "skipped", "missed", "unknown"]


@dataclass
class HabitConfig:
    name: str
    kind: HabitKind
    resolver: str | None = None  # required when kind == "auto"
    schedule: dict[str, Any] | None = None  # reserved; not honored this slice
    active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "resolver": self.resolver,
            "schedule": self.schedule,
            "active": self.active,
            "created_at": self.created_at,
        }


async def create_habit(db: AsyncDatabase, cfg: HabitConfig) -> str:
    res = await db["habits"].insert_one(cfg.to_dict())
    return str(res.inserted_id)


async def update_habit(
    db: AsyncDatabase, habit_id: str, patch: dict[str, Any],
) -> None:
    await db["habits"].update_one(
        {"_id": ObjectId(habit_id)},
        {"$set": patch},
    )


async def list_habits(db: AsyncDatabase) -> list[dict[str, Any]]:
    cur = db["habits"].find().sort("created_at", 1)
    out: list[dict[str, Any]] = []
    async for d in cur:
        d["id"] = str(d.pop("_id"))
        out.append(d)
    return out


async def get_active_habits(db: AsyncDatabase) -> list[dict[str, Any]]:
    rows = await list_habits(db)
    return [r for r in rows if r.get("active", True)]


async def get_habit_by_name(
    db: AsyncDatabase, name: str,
) -> dict[str, Any] | None:
    d = await db["habits"].find_one({"name": name})
    if d is None:
        return None
    d["id"] = str(d.pop("_id"))
    return d


async def mark_status(
    db: AsyncDatabase,
    habit_id: str,
    local_date: date,
    *,
    status: HabitStatusValue,
    source: Literal["auto", "manual", "coach"],
) -> None:
    await db["habit_status"].update_one(
        {"habit_id": habit_id, "local_date": local_date.isoformat()},
        {
            "$set": {
                "status": status,
                "source": source,
                "noted_at": datetime.now(UTC),
            },
        },
        upsert=True,
    )


async def status_for_day(
    db: AsyncDatabase, habit_id: str, local_date: date,
) -> dict[str, Any] | None:
    return await db["habit_status"].find_one(
        {"habit_id": habit_id, "local_date": local_date.isoformat()},
    )
```

- [ ] **Step 4: Run tests**

```
cd services/api && .venv/bin/pytest tests/test_habits.py -v
```

Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/coach/habits.py services/api/tests/test_habits.py
git commit -m "feat(habits): add config + daily status repos"
```

---

### Task 2: Auto resolvers (`bed_by_10`, `vitamins`) and today-status compose

**Files:**
- Modify: `services/api/app/services/coach/habits.py`
- Modify: `services/api/tests/test_habits.py`

Resolvers map a habit row + a local date + the db to a status dict. They live in a small registry inside `habits.py`. `bed_by_10` reads `metrics_sleep` for the night ending on `local_date` and compares onset to 22:00 local. `vitamins` checks the vitamins router's `count_vitamins_today` against the day.

`compose_today` is the entry point: walks all active habits, runs the resolver for `auto`, reads `habit_status` for `manual`, and emits `unknown` for `none` (or for `auto` resolvers that return None).

- [ ] **Step 1: Write the failing tests**

Append to `services/api/tests/test_habits.py`:

```python
from datetime import timedelta
from zoneinfo import ZoneInfo

from app.models.metrics import Sleep
from app.services.coach.habits import (
    RESOLVERS,
    compose_today,
)
from app.services.metrics_repo import MetricsRepo


async def test_bed_by_10_resolver_done_when_onset_before_2200(mock_db):
    repo = MetricsRepo(mock_db)
    # Sleep onset at 21:30 Chicago local (= 02:30 UTC the next day).
    chicago = ZoneInfo("America/Chicago")
    local_d = date(2026, 5, 10)
    onset_local = datetime(2026, 5, 10, 21, 30, tzinfo=chicago)
    await repo.insert_sleep(Sleep(
        ts=onset_local.astimezone(UTC),
        duration_s=27000, deep_s=3600, rem_s=5400, light_s=16000, awake_s=2000,
        score=80, source="garmin", source_id="s:1",
    ))
    out = await RESOLVERS["bed_by_10"](mock_db, local_d, tz=chicago)
    assert out == "done"


async def test_bed_by_10_resolver_missed_when_onset_after_2200(mock_db):
    repo = MetricsRepo(mock_db)
    chicago = ZoneInfo("America/Chicago")
    local_d = date(2026, 5, 10)
    onset_local = datetime(2026, 5, 10, 22, 30, tzinfo=chicago)
    await repo.insert_sleep(Sleep(
        ts=onset_local.astimezone(UTC),
        duration_s=27000, deep_s=3600, rem_s=5400, light_s=16000, awake_s=2000,
        score=80, source="garmin", source_id="s:2",
    ))
    out = await RESOLVERS["bed_by_10"](mock_db, local_d, tz=chicago)
    assert out == "missed"


async def test_bed_by_10_resolver_unknown_when_no_sleep(mock_db):
    chicago = ZoneInfo("America/Chicago")
    out = await RESOLVERS["bed_by_10"](mock_db, date(2026, 5, 10), tz=chicago)
    assert out == "unknown"


async def test_vitamins_resolver_done_when_logged_today(mock_db):
    chicago = ZoneInfo("America/Chicago")
    local_d = date(2026, 5, 10)
    # Insert a vitamins meal entry at noon local.
    noon_local = datetime(2026, 5, 10, 12, 0, tzinfo=chicago)
    await mock_db["meal_entries"].insert_one({
        "ts": noon_local.astimezone(UTC),
        "food_name": "Vitamins", "quantity_g": 1.0, "slot": "supplement",
        "macros": {},
    })
    out = await RESOLVERS["vitamins"](mock_db, local_d, tz=chicago)
    assert out == "done"


async def test_vitamins_resolver_missed_when_not_logged(mock_db):
    chicago = ZoneInfo("America/Chicago")
    out = await RESOLVERS["vitamins"](mock_db, date(2026, 5, 10), tz=chicago)
    assert out == "missed"


async def test_compose_today_mixes_auto_manual_and_none(mock_db):
    chicago = ZoneInfo("America/Chicago")
    local_d = date(2026, 5, 10)
    h_auto = await create_habit(mock_db, HabitConfig(
        name="bed by 10", kind="auto", resolver="bed_by_10",
    ))
    h_manual = await create_habit(mock_db, HabitConfig(
        name="make the bed", kind="manual",
    ))
    h_none = await create_habit(mock_db, HabitConfig(
        name="walk after lunch", kind="none",
    ))
    # Manual habit marked done.
    await mark_status(mock_db, h_manual, local_d, status="done", source="manual")
    # Bed onset before 22:00 local.
    repo = MetricsRepo(mock_db)
    onset = datetime(2026, 5, 10, 21, 0, tzinfo=chicago)
    await repo.insert_sleep(Sleep(
        ts=onset.astimezone(UTC),
        duration_s=27000, deep_s=3600, rem_s=5400, light_s=16000, awake_s=2000,
        score=80, source="garmin", source_id="s:c",
    ))

    out = await compose_today(mock_db, local_d, tz=chicago)
    by_name = {h["name"]: h for h in out}
    assert by_name["bed by 10"]["status"] == "done"
    assert by_name["bed by 10"]["source"] == "auto"
    assert by_name["make the bed"]["status"] == "done"
    assert by_name["make the bed"]["source"] == "manual"
    assert by_name["walk after lunch"]["status"] == "unknown"
    assert by_name["walk after lunch"]["kind"] == "none"
```

- [ ] **Step 2: Run tests to verify failure**

```
cd services/api && .venv/bin/pytest tests/test_habits.py -v
```

Expected: FAIL with `ImportError` on `RESOLVERS`/`compose_today`.

- [ ] **Step 3: Implement resolvers + compose_today**

Append to `services/api/app/services/coach/habits.py`:

```python
from collections.abc import Awaitable, Callable
from datetime import time, timedelta
from zoneinfo import ZoneInfo


# Each resolver takes (db, local_date, *, tz) and returns a HabitStatusValue
# string (never None — use "unknown" if the data is missing).
ResolverFn = Callable[[AsyncDatabase, date], Awaitable[HabitStatusValue]]


BED_CUTOFF_HOUR = 22  # 22:00 local; deliberately not configurable yet


async def _bed_by_10_resolver(
    db: AsyncDatabase, local_date: date, *, tz: ZoneInfo,
) -> HabitStatusValue:
    """`done` if sleep onset was at or before 22:00 local on `local_date`."""
    # The Garmin sleep doc's `ts` is the onset (UTC). We look for any sleep
    # record whose onset falls between local-noon-of-`local_date` and
    # local-noon-the-next-day, then compare its local hour to the cutoff.
    day_start_local = datetime.combine(local_date, time(12, 0), tzinfo=tz)
    next_day_start_local = day_start_local + timedelta(days=1)
    start_utc = day_start_local.astimezone(UTC)
    end_utc = next_day_start_local.astimezone(UTC)
    doc = await db["metrics_sleep"].find_one(
        {"ts": {"$gte": start_utc, "$lt": end_utc}},
        sort=[("ts", 1)],
    )
    if doc is None:
        return "unknown"
    onset_local = doc["ts"].astimezone(tz)
    cutoff = datetime.combine(
        onset_local.date(), time(BED_CUTOFF_HOUR, 0), tzinfo=tz,
    )
    return "done" if onset_local <= cutoff else "missed"


async def _vitamins_resolver(
    db: AsyncDatabase, local_date: date, *, tz: ZoneInfo,
) -> HabitStatusValue:
    """`done` if any vitamins entry was logged inside the local day."""
    day_start_local = datetime.combine(local_date, time.min, tzinfo=tz)
    next_day_local = day_start_local + timedelta(days=1)
    start_utc = day_start_local.astimezone(UTC)
    end_utc = next_day_local.astimezone(UTC)
    doc = await db["meal_entries"].find_one({
        "food_name": "Vitamins",
        "ts": {"$gte": start_utc, "$lt": end_utc},
    })
    return "done" if doc is not None else "missed"


RESOLVERS: dict[str, ResolverFn] = {
    "bed_by_10": _bed_by_10_resolver,
    "vitamins": _vitamins_resolver,
}


async def compose_today(
    db: AsyncDatabase, local_date: date, *, tz: ZoneInfo,
) -> list[dict[str, Any]]:
    """Return today's status for every active habit.

    Each item is `{id, name, kind, status, source, resolver}`:
    - `auto` habits run their resolver (source = "auto").
    - `manual` habits read `habit_status` for the day (source = "manual" if set, else "unknown").
    - `none` habits are listed with status "unknown".
    """
    habits = await get_active_habits(db)
    out: list[dict[str, Any]] = []
    for h in habits:
        entry: dict[str, Any] = {
            "id": h["id"],
            "name": h["name"],
            "kind": h["kind"],
            "resolver": h.get("resolver"),
        }
        if h["kind"] == "auto":
            resolver_name = h.get("resolver") or ""
            fn = RESOLVERS.get(resolver_name)
            if fn is None:
                entry["status"] = "unknown"
                entry["source"] = "auto"
            else:
                entry["status"] = await fn(db, local_date, tz=tz)
                entry["source"] = "auto"
        elif h["kind"] == "manual":
            row = await status_for_day(db, h["id"], local_date)
            if row is None:
                entry["status"] = "unknown"
                entry["source"] = "manual"
            else:
                entry["status"] = row["status"]
                entry["source"] = row["source"]
        else:  # none
            entry["status"] = "unknown"
            entry["source"] = "none"
        out.append(entry)
    return out
```

- [ ] **Step 4: Run tests**

```
cd services/api && .venv/bin/pytest tests/test_habits.py -v
```

Expected: 11 PASS total in `test_habits.py`.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/coach/habits.py services/api/tests/test_habits.py
git commit -m "feat(habits): bed_by_10 + vitamins resolvers, compose_today"
```

---

### Task 3: Habits REST API

**Files:**
- Create: `services/api/app/routers/habits.py`
- Create: `services/api/tests/test_habits_router.py`
- Modify: `services/api/app/main.py`

Endpoints (all under `/habits`, all `require_api_key`):
- `GET /habits` — list all habits (active + inactive).
- `POST /habits` — create a habit.
- `PATCH /habits/{id}` — update name/active/kind/resolver.
- `GET /habits/today` — today's status per active habit (uses `TZ` env var for the local day).
- `POST /habits/{id}/status` — mark status for today (or a passed-in local date).

- [ ] **Step 1: Write the failing tests**

Create `services/api/tests/test_habits_router.py`:

```python
"""Habits router integration tests."""

HEADERS = {"X-API-Key": "test-key"}


async def test_create_and_list_habits(client):
    r = await client.post("/habits", headers=HEADERS, json={
        "name": "brush teeth", "kind": "manual",
    })
    assert r.status_code == 201, r.text
    hid = r.json()["id"]
    assert hid

    r = await client.get("/habits", headers=HEADERS)
    assert r.status_code == 200
    rows = r.json()
    assert any(h["name"] == "brush teeth" for h in rows)


async def test_create_auto_habit_requires_resolver(client):
    r = await client.post("/habits", headers=HEADERS, json={
        "name": "bed by 10", "kind": "auto",
    })
    assert r.status_code == 400


async def test_create_auto_habit_with_unknown_resolver_rejected(client):
    r = await client.post("/habits", headers=HEADERS, json={
        "name": "weird", "kind": "auto", "resolver": "nope",
    })
    assert r.status_code == 400


async def test_patch_habit_can_deactivate(client):
    r = await client.post("/habits", headers=HEADERS, json={
        "name": "old habit", "kind": "manual",
    })
    hid = r.json()["id"]
    r = await client.patch(
        f"/habits/{hid}", headers=HEADERS, json={"active": False},
    )
    assert r.status_code == 200
    assert r.json()["active"] is False


async def test_today_returns_active_habits_with_status(client, monkeypatch):
    monkeypatch.setenv("TZ", "America/Chicago")
    await client.post("/habits", headers=HEADERS, json={
        "name": "make the bed", "kind": "manual",
    })
    r = await client.get("/habits/today", headers=HEADERS)
    assert r.status_code == 200
    rows = r.json()
    assert any(h["name"] == "make the bed" for h in rows)
    bed = next(h for h in rows if h["name"] == "make the bed")
    assert bed["status"] == "unknown"
    assert bed["kind"] == "manual"


async def test_status_post_marks_manual_done(client, monkeypatch):
    monkeypatch.setenv("TZ", "America/Chicago")
    r = await client.post("/habits", headers=HEADERS, json={
        "name": "make the bed", "kind": "manual",
    })
    hid = r.json()["id"]
    r = await client.post(
        f"/habits/{hid}/status", headers=HEADERS,
        json={"status": "done"},
    )
    assert r.status_code == 200, r.text
    r = await client.get("/habits/today", headers=HEADERS)
    bed = next(h for h in r.json() if h["name"] == "make the bed")
    assert bed["status"] == "done"
    assert bed["source"] == "manual"


async def test_status_400_on_bad_status_value(client):
    r = await client.post("/habits", headers=HEADERS, json={
        "name": "x", "kind": "manual",
    })
    hid = r.json()["id"]
    r = await client.post(
        f"/habits/{hid}/status", headers=HEADERS,
        json={"status": "bogus"},
    )
    assert r.status_code == 422  # FastAPI validation
```

- [ ] **Step 2: Run tests to verify failure**

```
cd services/api && .venv/bin/pytest tests/test_habits_router.py -v
```

Expected: FAIL (404 on `/habits` since the router doesn't exist yet).

- [ ] **Step 3: Implement the router**

Create `services/api/app/routers/habits.py`:

```python
"""Habits REST API."""
from __future__ import annotations

import os
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bson.errors import InvalidId
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.auth import require_api_key
from app.services.coach.habits import (
    RESOLVERS,
    HabitConfig,
    compose_today,
    create_habit,
    list_habits,
    mark_status,
    update_habit,
)

router = APIRouter(prefix="/habits", dependencies=[Depends(require_api_key)])


def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except (InvalidId, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid id: {s}") from e


def _resolve_tz() -> ZoneInfo:
    tz_name = os.environ.get("TZ") or "UTC"
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


class CreateHabitReq(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["auto", "manual", "none"]
    resolver: str | None = None


class PatchHabitReq(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    active: bool | None = None
    kind: Literal["auto", "manual", "none"] | None = None
    resolver: str | None = None


class StatusReq(BaseModel):
    status: Literal["done", "skipped", "missed", "unknown"]
    local_date: str | None = None  # YYYY-MM-DD; defaults to today (local tz)


@router.get("")
async def list_(request: Request) -> list[dict[str, Any]]:
    return await list_habits(request.app.state.db)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(req: CreateHabitReq, request: Request) -> dict[str, Any]:
    if req.kind == "auto":
        if not req.resolver:
            raise HTTPException(
                status_code=400, detail="auto habits require a resolver name",
            )
        if req.resolver not in RESOLVERS:
            raise HTTPException(
                status_code=400,
                detail=f"unknown resolver {req.resolver!r}; "
                       f"available: {sorted(RESOLVERS.keys())}",
            )
    hid = await create_habit(
        request.app.state.db,
        HabitConfig(name=req.name, kind=req.kind, resolver=req.resolver),
    )
    return {"id": hid, "name": req.name, "kind": req.kind, "active": True}


@router.patch("/{habit_id}")
async def patch(
    habit_id: str, req: PatchHabitReq, request: Request,
) -> dict[str, Any]:
    _oid(habit_id)
    patch_doc: dict[str, Any] = {}
    if req.name is not None: patch_doc["name"] = req.name
    if req.active is not None: patch_doc["active"] = req.active
    if req.kind is not None: patch_doc["kind"] = req.kind
    if req.resolver is not None: patch_doc["resolver"] = req.resolver
    if not patch_doc:
        raise HTTPException(status_code=400, detail="nothing to patch")
    await update_habit(request.app.state.db, habit_id, patch_doc)
    doc = await request.app.state.db["habits"].find_one({"_id": ObjectId(habit_id)})
    if doc is None:
        raise HTTPException(status_code=404, detail="habit not found")
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.get("/today")
async def today(request: Request) -> list[dict[str, Any]]:
    tz = _resolve_tz()
    local_today = datetime.now(UTC).astimezone(tz).date()
    return await compose_today(request.app.state.db, local_today, tz=tz)


@router.post("/{habit_id}/status")
async def post_status(
    habit_id: str, req: StatusReq, request: Request,
) -> dict[str, Any]:
    _oid(habit_id)
    tz = _resolve_tz()
    if req.local_date:
        try:
            d = date.fromisoformat(req.local_date)
        except ValueError as e:
            raise HTTPException(
                status_code=400, detail=f"bad local_date: {e}",
            ) from e
    else:
        d = datetime.now(UTC).astimezone(tz).date()
    await mark_status(
        request.app.state.db, habit_id, d,
        status=req.status, source="manual",
    )
    return {"habit_id": habit_id, "local_date": d.isoformat(), "status": req.status}
```

- [ ] **Step 4: Mount the router in `services/api/app/main.py`**

Find the block where existing routers are imported and included (look for `from app.routers import ...` and `app.include_router(...)`). Add the import and include for the new habits router. Place them logically grouped with the other coach-adjacent routers.

For the import:
```python
from app.routers import habits as habits_router
```
For the include:
```python
app.include_router(habits_router.router)
```

(Names may already exist with slightly different conventions in the file — match the existing style. If the file uses `from app.routers.coach import router as coach_router` instead of importing the module, adapt accordingly.)

- [ ] **Step 5: Run the tests**

```
cd services/api && .venv/bin/pytest tests/test_habits_router.py -v
```

Expected: 7 PASS.

- [ ] **Step 6: Run the full suite**

```
cd services/api && .venv/bin/pytest -q
```

Expected: ~250 PASS (232 baseline + 11 from Tasks 1-2 + 7 here).

- [ ] **Step 7: Commit**

```bash
git add services/api/app/routers/habits.py services/api/app/main.py services/api/tests/test_habits_router.py
git commit -m "feat(habits): REST API (list/create/patch/today/status)"
```

---

### Task 4: `build_findings` carries `habit_status_today`

**Files:**
- Modify: `services/api/app/services/coach/context.py`
- Modify: `services/api/tests/test_findings.py`

`Findings` gains a `habits` field listing today's habit statuses (the same shape `/habits/today` returns). The brief sees them; the chat agent loop sees them (because it builds Findings each turn).

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_findings.py`:

```python
from app.services.coach.habits import HabitConfig, create_habit


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
```

- [ ] **Step 2: Run it to verify it fails**

```
cd services/api && .venv/bin/pytest tests/test_findings.py::test_build_findings_includes_active_habits -v
```

Expected: FAIL — `Findings` has no `habits` field.

- [ ] **Step 3: Add `habits` to `Findings` and populate it from `compose_today`**

In `services/api/app/services/coach/context.py`:

Add the new field to the `Findings` dataclass (after `local`):

```python
@dataclass
class Findings:
    snapshot: dict[str, Any] = field(default_factory=dict)
    food_totals: dict[str, Any] = field(default_factory=dict)
    targets: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    on_track: list[str] = field(default_factory=list)
    attention: list[str] = field(default_factory=list)
    local: dict[str, Any] = field(default_factory=dict)
    habits: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

At the end of `build_findings`, before constructing and returning `Findings`, add:

```python
    from app.services.coach.habits import compose_today  # noqa: PLC0415
    import os  # noqa: PLC0415
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError  # noqa: PLC0415

    tz_name = os.environ.get("TZ") or "UTC"
    try:
        local_tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        local_tz = ZoneInfo("UTC")
    local_today_date = (day_start.astimezone(local_tz)).date()
    habits_today = await compose_today(db, local_today_date, tz=local_tz)
```

Wait — `build_findings` doesn't currently receive `db` directly; it receives `metrics_repo` and `food_repo`. Both have a `.db` attribute. Use one of them — `metrics_repo.db`.

So the correct addition is:

```python
    from app.services.coach.habits import compose_today  # noqa: PLC0415
    import os  # noqa: PLC0415
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError  # noqa: PLC0415

    tz_name = os.environ.get("TZ") or "UTC"
    try:
        local_tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        local_tz = ZoneInfo("UTC")
    local_today_date = day_start.astimezone(local_tz).date()
    habits_today = await compose_today(metrics_repo.db, local_today_date, tz=local_tz)
```

And include `habits=habits_today` in the `Findings(...)` constructor at the end:

```python
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
    )
```

- [ ] **Step 4: Run the test**

```
cd services/api && .venv/bin/pytest tests/test_findings.py::test_build_findings_includes_active_habits -v
```

Expected: PASS.

- [ ] **Step 5: Run the full findings + coach test files**

```
cd services/api && .venv/bin/pytest tests/test_findings.py tests/test_coach.py -v
```

Expected: all PASS. The brief tests should keep working because `habits` is just an additional field with empty default.

- [ ] **Step 6: Run the full suite**

```
cd services/api && .venv/bin/pytest -q
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add services/api/app/services/coach/context.py services/api/tests/test_findings.py
git commit -m "feat(coach): Findings carries today's habit statuses"
```

---

### Task 5: `habit_status` and `mark_habit_done` tools

**Files:**
- Modify: `services/api/app/services/coach/tools.py`
- Modify: `services/api/tests/test_coach_tools.py`

`habit_status(name, days_back=7)` returns the last `days_back` days of status for a habit by name.
`mark_habit_done(name, local_date=None)` marks a manual habit as done for the given date (default = today, local).

Both tools refuse to act on `auto` habits (use the resolver instead) and on unknown names.

- [ ] **Step 1: Write the failing tests**

Append to `services/api/tests/test_coach_tools.py`:

```python
from datetime import date as _date

from app.services.coach.habits import HabitConfig, create_habit, mark_status


async def test_habit_status_tool_returns_history(mock_db):
    hid = await create_habit(mock_db, HabitConfig(
        name="brush teeth", kind="manual",
    ))
    today = _date(2026, 5, 10)
    await mark_status(mock_db, hid, today, status="done", source="manual")
    out = await dispatch(mock_db, "habit_status", {
        "name": "brush teeth", "days_back": 7,
    })
    assert "error" not in out, out
    assert out["name"] == "brush teeth"
    assert isinstance(out["history"], list)
    assert any(d["status"] == "done" for d in out["history"])


async def test_habit_status_unknown_name(mock_db):
    out = await dispatch(mock_db, "habit_status", {
        "name": "nope", "days_back": 7,
    })
    assert "error" in out


async def test_mark_habit_done_tool_marks_manual_habit(mock_db):
    hid = await create_habit(mock_db, HabitConfig(
        name="make the bed", kind="manual",
    ))
    out = await dispatch(mock_db, "mark_habit_done", {"name": "make the bed"})
    assert "error" not in out, out
    assert out["status"] == "done"
    # Verify Mongo state.
    rows = [d async for d in mock_db["habit_status"].find({"habit_id": hid})]
    assert len(rows) == 1
    assert rows[0]["status"] == "done"
    assert rows[0]["source"] == "coach"


async def test_mark_habit_done_tool_refuses_auto_habit(mock_db):
    await create_habit(mock_db, HabitConfig(
        name="bed by 10", kind="auto", resolver="bed_by_10",
    ))
    out = await dispatch(mock_db, "mark_habit_done", {"name": "bed by 10"})
    assert "error" in out
    assert "auto" in out["error"].lower()
```

- [ ] **Step 2: Run them to verify failure**

```
cd services/api && .venv/bin/pytest tests/test_coach_tools.py -v
```

Expected: 4 new FAILs (unknown tool errors from dispatch).

- [ ] **Step 3: Register the tools**

In `services/api/app/services/coach/tools.py`, add two new tool functions and append to `REGISTRY`:

```python
async def _habit_status(
    db: AsyncDatabase, *, name: str, days_back: int = 7,
) -> dict[str, Any]:
    from datetime import UTC, date, datetime, timedelta  # noqa: PLC0415

    from app.services.coach.habits import (  # noqa: PLC0415
        get_habit_by_name,
        status_for_day,
    )

    habit = await get_habit_by_name(db, name)
    if habit is None:
        raise ToolError(f"no habit named {name!r}")
    today = datetime.now(UTC).date()
    out: list[dict[str, Any]] = []
    for i in range(days_back):
        d = today - timedelta(days=i)
        row = await status_for_day(db, habit["id"], d)
        out.append({
            "date": d.isoformat(),
            "status": row["status"] if row else "unknown",
            "source": row["source"] if row else None,
        })
    return {"name": habit["name"], "kind": habit["kind"], "history": out}


async def _mark_habit_done(
    db: AsyncDatabase, *, name: str, local_date: str | None = None,
) -> dict[str, Any]:
    from datetime import UTC, date, datetime  # noqa: PLC0415

    from app.services.coach.habits import (  # noqa: PLC0415
        get_habit_by_name,
        mark_status,
    )

    habit = await get_habit_by_name(db, name)
    if habit is None:
        raise ToolError(f"no habit named {name!r}")
    if habit["kind"] == "auto":
        raise ToolError(
            f"{name!r} is an auto habit — its status is derived from data, "
            "not toggled manually",
        )
    if local_date:
        try:
            d = date.fromisoformat(local_date)
        except ValueError as e:
            raise ToolError(f"bad local_date: {e}") from e
    else:
        d = datetime.now(UTC).date()
    await mark_status(db, habit["id"], d, status="done", source="coach")
    return {"name": habit["name"], "local_date": d.isoformat(), "status": "done"}


REGISTRY.update({
    "habit_status": {
        "fn": _habit_status,
        "schema": {
            "type": "function",
            "function": {
                "name": "habit_status",
                "description": (
                    "Get the last N days of status for a named habit "
                    "(returns one entry per day, newest first)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "days_back": {
                            "type": "integer", "minimum": 1, "maximum": 30,
                        },
                    },
                    "required": ["name"],
                },
            },
        },
    },
    "mark_habit_done": {
        "fn": _mark_habit_done,
        "schema": {
            "type": "function",
            "function": {
                "name": "mark_habit_done",
                "description": (
                    "Mark a manual habit as done for today (or a specific "
                    "local_date, YYYY-MM-DD). Refuses to act on auto habits."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "local_date": {
                            "type": "string",
                            "description": "YYYY-MM-DD, omit for today",
                        },
                    },
                    "required": ["name"],
                },
            },
        },
    },
})
```

- [ ] **Step 4: Run the tool tests**

```
cd services/api && .venv/bin/pytest tests/test_coach_tools.py -v
```

Expected: all PASS.

- [ ] **Step 5: Run the full suite**

```
cd services/api && .venv/bin/pytest -q
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add services/api/app/services/coach/tools.py services/api/tests/test_coach_tools.py
git commit -m "feat(coach): habit_status and mark_habit_done tools"
```

---

### Task 6: Re-export habits from the coach package

**Files:**
- Modify: `services/api/app/services/coach/__init__.py`

- [ ] **Step 1: Add the habits exports**

Append a new import block to `services/api/app/services/coach/__init__.py`:

```python
from app.services.coach.habits import (  # noqa: F401
    RESOLVERS,
    HabitConfig,
    compose_today,
    create_habit,
    get_active_habits,
    get_habit_by_name,
    list_habits,
    mark_status,
    status_for_day,
    update_habit,
)
```

- [ ] **Step 2: Run the suite**

```
cd services/api && .venv/bin/pytest -q
```

Expected: same PASS count (no behavior change).

- [ ] **Step 3: Commit**

```bash
git add services/api/app/services/coach/__init__.py
git commit -m "refactor(coach): re-export habits helpers from package __init__"
```

---

### Task 7: FE types

**Files:**
- Modify: `services/web/src/api/types.ts`

- [ ] **Step 1: Add types**

Append (after the existing CoachThread types):

```typescript
export type HabitKind = "auto" | "manual" | "none";
export type HabitStatusValue = "done" | "skipped" | "missed" | "unknown";

export interface Habit {
  id: string;
  name: string;
  kind: HabitKind;
  resolver?: string | null;
  active: boolean;
  created_at?: string;
}

export interface HabitStatusToday {
  id: string;
  name: string;
  kind: HabitKind;
  resolver?: string | null;
  status: HabitStatusValue;
  source: "auto" | "manual" | "coach" | "none";
}

export interface CreateHabitRequest {
  name: string;
  kind: HabitKind;
  resolver?: string;
}
```

- [ ] **Step 2: Typecheck**

```
cd services/web && npx tsc -b --noEmit
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add services/web/src/api/types.ts
git commit -m "feat(web): add Habit / HabitStatusToday types"
```

---

### Task 8: FE api client methods

**Files:**
- Modify: `services/web/src/api/client.ts`

- [ ] **Step 1: Add `Habit, HabitStatusToday, HabitStatusValue` to the type imports**

Find the existing top-of-file `import type {...} from "./types"` block and add the three new names alphabetically.

- [ ] **Step 2: Add methods to `export const api`**

Add after the coach-thread methods:

```typescript
  habitsList: () => get<Habit[]>("/habits"),
  habitsToday: () => get<HabitStatusToday[]>("/habits/today"),
  habitCreate: (name: string, kind: Habit["kind"], resolver?: string) =>
    post<Habit>("/habits", { name, kind, ...(resolver ? { resolver } : {}) }),
  habitMarkStatus: (habitId: string, status: HabitStatusValue) =>
    post<{ habit_id: string; status: HabitStatusValue }>(
      `/habits/${habitId}/status`,
      { status },
    ),
```

- [ ] **Step 3: Typecheck**

```
cd services/web && npx tsc -b --noEmit
```

Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add services/web/src/api/client.ts
git commit -m "feat(web): api.habitsList/habitsToday/habitCreate/habitMarkStatus"
```

---

### Task 9: HabitsCard component

**Files:**
- Create: `services/web/src/components/HabitsCard.tsx`
- Create: `services/web/src/components/HabitsCard.test.tsx`

The card shows today's habit list with status indicators, lets the user mark manual habits done, and has a tiny "+ New habit" form (name + kind dropdown; resolver optional). Auto habit rows are read-only (status comes from resolver).

- [ ] **Step 1: Write a minimal failing test**

Create `services/web/src/components/HabitsCard.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { HabitsCard } from "./HabitsCard";

vi.mock("../api/client", () => ({
  api: {
    habitsToday: vi.fn().mockResolvedValue([
      { id: "h1", name: "make the bed", kind: "manual", status: "unknown", source: "manual" },
      { id: "h2", name: "bed by 10", kind: "auto", status: "done", source: "auto", resolver: "bed_by_10" },
    ]),
    habitCreate: vi.fn(),
    habitMarkStatus: vi.fn(),
  },
}));

function wrap(node: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

describe("HabitsCard", () => {
  it("lists today's habits with status indicators", async () => {
    render(wrap(<HabitsCard />));
    expect(await screen.findByText(/make the bed/i)).toBeTruthy();
    expect(screen.getByText(/bed by 10/i)).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run it to verify failure**

```
cd services/web && npm test -- --run src/components/HabitsCard.test.tsx
```

Expected: FAIL — component does not exist.

- [ ] **Step 3: Implement `HabitsCard`**

Create `services/web/src/components/HabitsCard.tsx`:

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { Habit, HabitStatusToday } from "../api/types";


function statusBadge(s: HabitStatusToday["status"]): string {
  if (s === "done") return "✅";
  if (s === "missed") return "❌";
  if (s === "skipped") return "⏭";
  return "·";  // unknown
}

function HabitRow({ h, onToggle, busy }: {
  h: HabitStatusToday;
  onToggle: (id: string) => void;
  busy: boolean;
}) {
  const isManual = h.kind === "manual";
  const isDone = h.status === "done";
  return (
    <div className="flex items-center justify-between py-2">
      <div>
        <div className="text-sm">{h.name}</div>
        <div className="text-[11px] text-neutral-500">
          {h.kind}{h.resolver ? ` · ${h.resolver}` : ""}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-base">{statusBadge(h.status)}</span>
        {isManual && (
          <button
            type="button"
            onClick={() => onToggle(h.id)}
            disabled={busy}
            className={
              "text-xs px-2 py-1 rounded min-h-[32px] " +
              (isDone
                ? "bg-emerald-700 text-white"
                : "bg-neutral-800 active:bg-neutral-700")
            }
          >
            {isDone ? "done" : "mark done"}
          </button>
        )}
      </div>
    </div>
  );
}

function NewHabitForm({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<Habit["kind"]>("manual");
  const [resolver, setResolver] = useState("");
  const create = useMutation({
    mutationFn: () =>
      api.habitCreate(name.trim(), kind, resolver.trim() || undefined),
    onSuccess: () => {
      setName(""); setResolver("");
      onCreated();
    },
  });
  return (
    <form
      onSubmit={e => { e.preventDefault(); if (name.trim()) create.mutate(); }}
      className="space-y-2 border-t border-neutral-800 pt-3"
    >
      <div className="text-xs uppercase tracking-wide text-neutral-500">
        Add habit
      </div>
      <div className="flex gap-2">
        <input
          type="text"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="habit name"
          className="flex-1 text-sm px-2 py-2 rounded bg-neutral-800 border border-neutral-700"
        />
        <select
          value={kind}
          onChange={e => setKind(e.target.value as Habit["kind"])}
          className="text-sm px-2 py-2 rounded bg-neutral-800 border border-neutral-700"
        >
          <option value="manual">manual</option>
          <option value="auto">auto</option>
          <option value="none">nudge only</option>
        </select>
      </div>
      {kind === "auto" && (
        <input
          type="text"
          value={resolver}
          onChange={e => setResolver(e.target.value)}
          placeholder="resolver name (e.g. bed_by_10)"
          className="w-full text-sm px-2 py-2 rounded bg-neutral-800 border border-neutral-700"
        />
      )}
      <button
        type="submit"
        disabled={create.isPending || !name.trim() || (kind === "auto" && !resolver.trim())}
        className="text-xs px-3 py-2 rounded bg-emerald-700 active:bg-emerald-800 disabled:opacity-50"
      >
        {create.isPending ? "adding…" : "add habit"}
      </button>
      {create.error && (
        <div className="text-xs text-red-400">{(create.error as Error).message}</div>
      )}
    </form>
  );
}

export function HabitsCard() {
  const qc = useQueryClient();
  const { data: habits = [], isLoading } = useQuery({
    queryKey: ["habits.today"],
    queryFn: api.habitsToday,
  });
  const toggle = useMutation({
    mutationFn: (id: string) => api.habitMarkStatus(id, "done"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["habits.today"] }),
  });
  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-4 space-y-2">
      <div className="text-xs uppercase tracking-wide text-neutral-400">
        Habits
      </div>
      {isLoading ? (
        <div className="text-xs text-neutral-500">loading…</div>
      ) : habits.length === 0 ? (
        <div className="text-xs text-neutral-500">no habits yet — add one below.</div>
      ) : (
        <div className="divide-y divide-neutral-800">
          {habits.map(h => (
            <HabitRow key={h.id} h={h} onToggle={id => toggle.mutate(id)} busy={toggle.isPending} />
          ))}
        </div>
      )}
      <NewHabitForm onCreated={() => qc.invalidateQueries({ queryKey: ["habits.today"] })} />
    </div>
  );
}
```

- [ ] **Step 4: Run the test**

```
cd services/web && npm test -- --run src/components/HabitsCard.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Run the full FE suite + typecheck**

```
cd services/web && npm test -- --run && npx tsc -b --noEmit
```

Expected: all PASS, typecheck clean.

- [ ] **Step 6: Commit**

```bash
git add services/web/src/components/HabitsCard.tsx services/web/src/components/HabitsCard.test.tsx
git commit -m "feat(web): HabitsCard — today list, toggle, add-habit form"
```

---

### Task 10: Wire `HabitsCard` into the More tab

**Files:**
- Modify: `services/web/src/pages/Dashboard.tsx`

- [ ] **Step 1: Add the import**

At the top of `services/web/src/pages/Dashboard.tsx`, add:

```tsx
import { HabitsCard } from "../components/HabitsCard";
```

- [ ] **Step 2: Render it inside `MoreTab`**

Find the `function MoreTab()` block. Inside the returned `<div className="space-y-4 sm:space-y-6">`, insert `<HabitsCard />` between `<TargetsCard />` and `<NotificationsSettings />`:

```tsx
      <TargetsCard />
      <HabitsCard />
      <NotificationsSettings />
```

- [ ] **Step 3: Run FE tests + typecheck**

```
cd services/web && npm test -- --run && npx tsc -b --noEmit
```

Expected: all PASS, typecheck clean.

- [ ] **Step 4: Commit**

```bash
git add services/web/src/pages/Dashboard.tsx
git commit -m "feat(web): render HabitsCard on the More tab"
```

---

### Task 11: Final verification + push

- [ ] **Step 1: Backend tests**

```
cd services/api && .venv/bin/pytest -q
```

Expected: all PASS (baseline 232 + ~25 new).

- [ ] **Step 2: Lint backend**

```
cd services/api && .venv/bin/ruff check app tests
```

Expected: 1 pre-existing baseline error in `tests/test_treadmill_aggregator.py`. Zero new errors. If you see new errors, fix inline. Common ones:
- `PLC0415` on function-local imports → add `# noqa: PLC0415` (already the pattern).
- `E501` on long schema description strings → wrap with parenthesized multi-line.
- `PLR2004` on magic numbers (`22`, `7`, `30`) → extract module-level constants if the number is meaningful.

- [ ] **Step 3: FE tests**

```
cd services/web && npm test -- --run
```

Expected: all PASS.

- [ ] **Step 4: FE typecheck**

```
cd services/web && npx tsc -b --noEmit
```

Expected: clean.

- [ ] **Step 5: Smoke-test optional**

If you have a running stack: open the dashboard, expand "More", confirm Habits card renders. Add a habit (`make the bed`, manual). Toggle done. Refresh, confirm status persists. If the coach can call tools, ask it to "mark my make-the-bed habit done"; verify the status updates.

- [ ] **Step 6: Push**

```bash
git push origin master
```

Watchtower picks up the rebuilt images in ~60s.

---

## Self-Review

**Spec coverage**

Slice 3 from the spec: "Habits config + resolvers + status repo + Habits page; `habit_status` and `mark_habit_done` tools."

- Habits collection (`habits`) + status (`habit_status`) — Task 1.
- Resolvers (`bed_by_10`, `vitamins`) + `compose_today` — Task 2.
- REST API endpoints — Task 3.
- Findings carries today's habit statuses — Task 4.
- `habit_status` + `mark_habit_done` tools — Task 5.
- Habits page (card on More tab) — Tasks 9-10.

**Deferred from this slice (explicit)**

- Habit `schedule` (`days_per_week`, `time_window`) — field reserved but no behavior yet.
- Configurable bed cutoff (currently hard-coded to 22:00 local).
- `mark_habit_skipped` / `mark_habit_missed` tools — not exposed; manual status route accepts any value.
- Habit reordering / delete (delete = `PATCH /habits/{id}` with `active: false`).
- Auto-seed of starter habits — user creates their own via the "+ New habit" form.

**Placeholder scan**

- No "TBD" / "TODO" / "fill in" anywhere in the plan body.
- Every code step has actual code.
- Every command has expected output.

**Type consistency**

- `HabitConfig` (Task 1) — used as the input to `create_habit` in Tasks 2-5.
- `RESOLVERS: dict[str, ResolverFn]` (Task 2) — referenced in Task 3 router validation and Task 5 tools.
- `compose_today(db, local_date, *, tz)` signature consistent across Tasks 2, 3, 4.
- FE `Habit` / `HabitStatusToday` (Task 7) match the JSON shape from Tasks 3 and 4.
- API method names (`habitsList`, `habitsToday`, `habitCreate`, `habitMarkStatus`) consistent between Task 8 and Task 9 usage.
