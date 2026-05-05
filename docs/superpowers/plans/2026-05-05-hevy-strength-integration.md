# Hevy Strength Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pull Hevy strength workouts (sessions + per-set detail) into the dashboard via webhook + cron-poll backstop, surface them in a new `/workouts` list reachable from the More tab.

**Architecture:** New `services/ingestor-hevy` container mirrors the Garmin ingestor pattern (poll `ingestion_log` for `requested` rows + cron schedule). Webhook endpoint in API enqueues; ingestor processes by re-fetching from Hevy. Strength data lands in existing `workouts` collection (summary) + new `strength_sets` collection (per-set). Frontend gets `/workouts` list and `/workouts/:source_id` detail under More.

**Tech Stack:** FastAPI, pymongo (async), Pydantic v2, httpx, APScheduler, React + react-router + Tailwind, vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-05-05-hevy-strength-integration-design.md`

---

## File Structure

**Created:**
- `services/ingestor-hevy/pyproject.toml`
- `services/ingestor-hevy/Dockerfile`
- `services/ingestor-hevy/app/__init__.py`
- `services/ingestor-hevy/app/config.py` — Settings (HEVY_API_KEY, mongo, schedule)
- `services/ingestor-hevy/app/models.py` — `Workout`, `StrengthSet` Pydantic models
- `services/ingestor-hevy/app/hevy_client.py` — httpx wrapper, api-key header
- `services/ingestor-hevy/app/mappers.py` — `map_workout`, `map_strength_sets`
- `services/ingestor-hevy/app/repo.py` — `HevyRepo` (upsert+version-check, cascade delete)
- `services/ingestor-hevy/app/runner.py` — `process_event`, `run_backfill`, `run_events_sync`
- `services/ingestor-hevy/app/main.py` — entry, scheduler, request poller
- `services/ingestor-hevy/tests/__init__.py`
- `services/ingestor-hevy/tests/test_mappers.py`
- `services/ingestor-hevy/tests/test_repo.py`
- `services/ingestor-hevy/tests/test_runner.py`
- `services/ingestor-hevy/tests/fixtures/workout_strength.json`
- `services/api/app/routers/webhooks.py` — `POST /webhooks/hevy`
- `services/api/tests/test_webhooks.py`
- `services/api/tests/test_workouts_detail.py`
- `services/web/src/pages/WorkoutList.tsx`
- `services/web/src/pages/WorkoutDetail.tsx`
- `services/web/src/components/WorkoutListRow.tsx`
- `services/web/src/components/StrengthSetTable.tsx`
- `tools/register-hevy-webhook.sh`

**Modified:**
- `services/api/app/db.py` — add `strength_sets` collection + indexes
- `services/api/app/routers/workouts.py` — add `GET /workouts/{source_id}`; list endpoint already returns new fields once they're written
- `services/api/app/main.py` — register webhooks router
- `services/api/app/config.py` — add `hevy_webhook_secret`
- `services/web/src/api/client.ts` — `getWorkout(sourceId)` method
- `services/web/src/api/types.ts` — `Workout` extra fields, `StrengthSet`, `WorkoutDetail`
- `services/web/src/router.tsx` — `/workouts`, `/workouts/:sourceId` routes; `/workout` redirect
- `services/web/src/pages/Dashboard.tsx` — More tab gets Workouts entry
- `services/web/src/components/ActiveWorkoutCard.tsx` — deep-link to `/workouts/:sourceId`
- `compose/docker-compose.yml` — add `ingestor-hevy` service
- `compose/.env.example` — already done; add `HEVY_WEBHOOK_SECRET=`
- `.github/workflows/build.yml` — build + push `hack-the-body-ingestor-hevy`

---

## Task 1: DB schema — `strength_sets` collection + new `workouts` fields

**Files:**
- Modify: `services/api/app/db.py`
- Test: `services/api/tests/test_db.py` (existing, adjust if present, else add a focused test)

- [ ] **Step 1: Write failing test** — confirm `strength_sets` collection exists and has the expected indexes after `ensure_collections`.

```python
# services/api/tests/test_db.py  (add this test; keep any existing ones)
import pytest
from mongomock_motor import AsyncMongoMockClient
from app.db import ensure_collections


@pytest.mark.asyncio
async def test_strength_sets_collection_and_indexes_created():
    client = AsyncMongoMockClient()
    db = client["htb_test"]
    await ensure_collections(db)
    assert "strength_sets" in await db.list_collection_names()
    indexes = await db["strength_sets"].index_information()
    # Composite child index for parent lookups
    assert any(
        spec["key"] == [("workout_source_id", 1), ("exercise_index", 1), ("set_index", 1)]
        for spec in indexes.values()
    )
    # Per-exercise time index for "all my pull-up sets" queries
    assert any(
        spec["key"] == [("exercise_template_id", 1), ("ts", -1)]
        for spec in indexes.values()
    )
```

- [ ] **Step 2: Run, expect FAIL**

```
cd services/api && .venv/bin/pytest tests/test_db.py -v
```

Expected: `KeyError`/`AssertionError` because `strength_sets` is missing.

- [ ] **Step 3: Edit `services/api/app/db.py`**

Add `"strength_sets"` to `REGULAR_COLLECTIONS`, then add the two indexes inside `ensure_collections` (alongside the existing `db["workouts"].create_index` block):

```python
REGULAR_COLLECTIONS = ["workouts", "user_profile", "ingestion_log",
                       "foods", "meal_templates", "coach_insights",
                       "push_subscriptions", "parse_feedback",
                       "strength_sets"]
```

```python
# inside ensure_collections, after the existing workouts/ingestion_log indexes:
await db["strength_sets"].create_index(
    [("workout_source_id", 1), ("exercise_index", 1), ("set_index", 1)],
    name="strength_sets_parent_order",
)
await db["strength_sets"].create_index(
    [("exercise_template_id", 1), ("ts", -1)],
    name="strength_sets_exercise_ts",
)
```

- [ ] **Step 4: Run, expect PASS**

```
cd services/api && .venv/bin/pytest tests/test_db.py -v
```

- [ ] **Step 5: Commit**

```
git add services/api/app/db.py services/api/tests/test_db.py
git commit -m "feat(db): add strength_sets collection with parent + exercise indexes"
```

---

## Task 2: API config — `hevy_webhook_secret`

**Files:**
- Modify: `services/api/app/config.py`

- [ ] **Step 1: Read current config to find where to add the field**

```
sed -n '1,80p' services/api/app/config.py
```

- [ ] **Step 2: Add `hevy_webhook_secret: str | None = None` to the Settings class**

In `services/api/app/config.py`, find the `Settings` class and add:

```python
    hevy_webhook_secret: str | None = None
```

(Pydantic-Settings reads `HEVY_WEBHOOK_SECRET` from the environment automatically because the field name maps to the upper-snake env var.)

- [ ] **Step 3: Verify it loads**

```
cd services/api && .venv/bin/python -c "from app.config import get_settings; print(get_settings().hevy_webhook_secret)"
```

Expected: `None` (no env var set).

- [ ] **Step 4: Commit**

```
git add services/api/app/config.py
git commit -m "feat(api): add hevy_webhook_secret setting"
```

---

## Task 3: Webhook endpoint — `POST /webhooks/hevy`

**Files:**
- Create: `services/api/app/routers/webhooks.py`
- Create: `services/api/tests/test_webhooks.py`
- Modify: `services/api/app/main.py` — register router

- [ ] **Step 1: Write failing tests**

```python
# services/api/tests/test_webhooks.py
import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
async def app_client():
    settings = Settings(
        api_key="test-key",
        mongo_url="mongodb://stub",
        mongo_db="htb_test",
        hevy_webhook_secret="webhook-secret",  # noqa: S106
    )
    app = create_app(settings=settings)
    # Replace the real Mongo client created by the lifespan with a mock.
    mock_client = AsyncMongoMockClient()
    app.state.mongo_client = mock_client
    app.state.db = mock_client["htb_test"]
    from app.db import ensure_collections
    await ensure_collections(app.state.db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, app


@pytest.mark.asyncio
async def test_webhook_rejects_missing_auth(app_client):
    ac, _ = app_client
    r = await ac.post("/webhooks/hevy", json={"event": "workout.created", "id": "abc"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_webhook_rejects_wrong_secret(app_client):
    ac, _ = app_client
    r = await ac.post(
        "/webhooks/hevy",
        json={"event": "workout.created", "id": "abc"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_webhook_accepts_valid_request_and_writes_log(app_client):
    ac, app = app_client
    r = await ac.post(
        "/webhooks/hevy",
        json={"event": "workout.updated", "id": "wkid-1"},
        headers={"Authorization": "Bearer webhook-secret"},
    )
    assert r.status_code == 204
    # ingestion_log row queued for the ingestor
    rows = [d async for d in app.state.db["ingestion_log"].find({"source": "hevy"})]
    assert len(rows) == 1
    assert rows[0]["status"] == "requested"
    assert rows[0]["payload"]["workout_id"] == "wkid-1"
    assert rows[0]["payload"]["event"] == "workout.updated"


@pytest.mark.asyncio
async def test_webhook_rejects_malformed_body(app_client):
    ac, _ = app_client
    r = await ac.post(
        "/webhooks/hevy",
        json={"random": "garbage"},
        headers={"Authorization": "Bearer webhook-secret"},
    )
    assert r.status_code == 422  # FastAPI validation error
```

- [ ] **Step 2: Run, expect FAIL**

```
cd services/api && .venv/bin/pytest tests/test_webhooks.py -v
```

Expected: 404 (no route).

- [ ] **Step 3: Create `services/api/app/routers/webhooks.py`**

```python
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class HevyEvent(BaseModel):
    event: Literal["workout.created", "workout.updated", "workout.deleted"]
    id: str


@router.post("/hevy", status_code=204)
async def hevy_webhook(
    payload: HevyEvent,
    request: Request,
    authorization: str | None = Header(default=None),
) -> Response:
    expected = request.app.state.settings.hevy_webhook_secret
    if not expected:
        # Webhook explicitly disabled — refuse all traffic to be safe.
        raise HTTPException(status_code=503, detail="hevy webhook not configured")
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="unauthorized")

    # Enqueue. Don't fetch synchronously — the ingestor handles that path
    # on its poll loop, identical to /admin/ingest/garmin.
    await request.app.state.db["ingestion_log"].insert_one({
        "source": "hevy",
        "status": "requested",
        "started_at": datetime.now(UTC),
        "payload": {"workout_id": payload.id, "event": payload.event},
    })
    return Response(status_code=204)
```

- [ ] **Step 4: Register the router in `services/api/app/main.py`**

Find the existing block:

```python
    from app.routers import (
        admin,
        auth,
        coach,
        foods,
        meals,
        metrics,
```

Add `webhooks` to the import (alphabetical) and `app.include_router(webhooks.router)` to the registration block (search for other `include_router` calls and add it nearby).

- [ ] **Step 5: Run tests, expect PASS**

```
cd services/api && .venv/bin/pytest tests/test_webhooks.py -v
```

- [ ] **Step 6: Commit**

```
git add services/api/app/routers/webhooks.py services/api/app/main.py services/api/tests/test_webhooks.py
git commit -m "feat(api): add hevy webhook endpoint with bearer auth"
```

---

## Task 4: Workout detail endpoint — `GET /workouts/{source_id}`

**Files:**
- Modify: `services/api/app/routers/workouts.py`
- Create: `services/api/tests/test_workouts_detail.py`

- [ ] **Step 1: Write failing tests**

```python
# services/api/tests/test_workouts_detail.py
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.config import Settings
from app.db import ensure_collections
from app.main import create_app


@pytest.fixture
async def client():
    settings = Settings(api_key="k", mongo_url="mongodb://stub", mongo_db="htb_test")
    app = create_app(settings=settings)
    mock = AsyncMongoMockClient()
    app.state.mongo_client = mock
    app.state.db = mock["htb_test"]
    await ensure_collections(app.state.db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                            headers={"X-API-Key": "k"}) as ac:
        yield ac, app.state.db


@pytest.mark.asyncio
async def test_get_workout_detail_strength_includes_exercises(client):
    ac, db = client
    await db["workouts"].insert_one({
        "ts": datetime(2026, 5, 4, 18, tzinfo=UTC),
        "activity_type": "strength",
        "duration_s": 2520,
        "source": "hevy",
        "source_id": "hevy:wk1",
        "title": "Push Day",
        "exercise_count": 2,
        "set_count": 3,
    })
    await db["strength_sets"].insert_many([
        {"workout_source_id": "hevy:wk1", "ts": datetime(2026, 5, 4, 18, tzinfo=UTC),
         "exercise_index": 0, "exercise_title": "Push Up",
         "exercise_template_id": "T1", "set_index": 0, "set_type": "normal",
         "reps": 12, "weight_kg": None},
        {"workout_source_id": "hevy:wk1", "ts": datetime(2026, 5, 4, 18, tzinfo=UTC),
         "exercise_index": 0, "exercise_title": "Push Up",
         "exercise_template_id": "T1", "set_index": 1, "set_type": "normal",
         "reps": 12, "weight_kg": None},
        {"workout_source_id": "hevy:wk1", "ts": datetime(2026, 5, 4, 18, tzinfo=UTC),
         "exercise_index": 1, "exercise_title": "Pull Up",
         "exercise_template_id": "T2", "set_index": 0, "set_type": "normal",
         "reps": 8, "weight_kg": None},
    ])
    r = await ac.get("/workouts/hevy:wk1")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Push Day"
    assert len(body["exercises"]) == 2
    assert body["exercises"][0]["title"] == "Push Up"
    assert len(body["exercises"][0]["sets"]) == 2
    assert body["exercises"][1]["title"] == "Pull Up"


@pytest.mark.asyncio
async def test_get_workout_detail_cardio_no_exercises_key(client):
    ac, db = client
    await db["workouts"].insert_one({
        "ts": datetime(2026, 5, 4, tzinfo=UTC),
        "activity_type": "running",
        "duration_s": 1800, "distance_m": 5000,
        "source": "garmin", "source_id": "garmin:activity:42",
    })
    r = await ac.get("/workouts/garmin:activity:42")
    assert r.status_code == 200
    body = r.json()
    assert body["activity_type"] == "running"
    assert body.get("exercises") in (None, [])  # absent or empty


@pytest.mark.asyncio
async def test_get_workout_detail_404(client):
    ac, _ = client
    r = await ac.get("/workouts/nonexistent:abc")
    assert r.status_code == 404
```

- [ ] **Step 2: Run, expect FAIL**

```
cd services/api && .venv/bin/pytest tests/test_workouts_detail.py -v
```

- [ ] **Step 3: Add the route to `services/api/app/routers/workouts.py`**

Add this **before** the existing `/active` and `/treadmill/samples` routes (so the path param doesn't accidentally swallow them — but FastAPI matches static paths before dynamic ones so order doesn't matter; place it near `list_workouts` for readability):

```python
@router.get("/{source_id:path}")
async def get_workout(request: Request, source_id: str):
    db = request.app.state.db
    doc = await db["workouts"].find_one({"source_id": source_id})
    if doc is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="workout not found")
    doc.pop("_id", None)

    if doc.get("activity_type") == "strength":
        sets_cursor = db["strength_sets"].find(
            {"workout_source_id": source_id},
        ).sort([("exercise_index", 1), ("set_index", 1)])
        exercises: list[dict] = []
        current: dict | None = None
        async for s in sets_cursor:
            s.pop("_id", None)
            if current is None or s["exercise_index"] != current["index"]:
                current = {
                    "index": s["exercise_index"],
                    "title": s["exercise_title"],
                    "template_id": s.get("exercise_template_id"),
                    "notes": s.get("notes"),
                    "superset_id": s.get("superset_id"),
                    "sets": [],
                }
                exercises.append(current)
            current["sets"].append({
                "set_index": s["set_index"],
                "set_type": s.get("set_type"),
                "reps": s.get("reps"),
                "weight_kg": s.get("weight_kg"),
                "distance_m": s.get("distance_m"),
                "duration_s": s.get("duration_s"),
                "rpe": s.get("rpe"),
            })
        doc["exercises"] = exercises

    return doc
```

**Important:** the existing `/active`, `/treadmill/samples` routes are static and FastAPI matches them first — but using `{source_id:path}` is needed because the source_id contains `:` (e.g. `hevy:wkid-1`), and a default path converter accepts `:`. Test that `/active` still works after this change.

- [ ] **Step 4: Verify `/active` still routes correctly — quick sanity test**

Add to `test_workouts_detail.py`:

```python
@pytest.mark.asyncio
async def test_active_route_still_works_after_dynamic_param(client):
    ac, _ = client
    r = await ac.get("/workouts/active")
    # Should be 204 (no active treadmill) or 200, never 404 routed to detail.
    assert r.status_code in (200, 204)
```

If this fails with a 404, FastAPI is matching the dynamic route. Fix by **placing the dynamic route LAST** in the router file (after all static `/active`, `/treadmill/...` routes).

- [ ] **Step 5: Run, expect PASS**

```
cd services/api && .venv/bin/pytest tests/test_workouts_detail.py -v
```

- [ ] **Step 6: Commit**

```
git add services/api/app/routers/workouts.py services/api/tests/test_workouts_detail.py
git commit -m "feat(api): add GET /workouts/{source_id} with strength exercise grouping"
```

---

## Task 5: Hevy ingestor — pyproject + Dockerfile + skeleton

**Files:**
- Create: `services/ingestor-hevy/pyproject.toml`
- Create: `services/ingestor-hevy/Dockerfile`
- Create: `services/ingestor-hevy/app/__init__.py`
- Create: `services/ingestor-hevy/tests/__init__.py`

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[project]
name = "hack-the-body-ingestor-hevy"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "pymongo>=4.9",
  "pydantic>=2.9",
  "pydantic-settings>=2.5",
  "apscheduler>=3.10",
  "httpx>=0.27",
  "python-dateutil>=2.9",
  "tenacity>=9.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.3",
  "pytest-asyncio>=0.24",
  "mongomock-motor>=0.0.34",
  "pytest-httpx>=0.32",
  "ruff>=0.7",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["ALL"]
ignore = [
  "D", "ANN", "FA", "COM812", "ISC001",
  "EM101", "EM102", "TRY003", "G004", "BLE001", "PLR0913",
  "RUF012", "S311", "TD", "FIX", "TRY300", "TC", "PGH003", "ERA001",
]

[tool.ruff.lint.mccabe]
max-complexity = 10

[tool.ruff.lint.pylint]
max-args = 8

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "S105", "S106", "PLR2004", "PT", "INP001", "SLF001"]
```

- [ ] **Step 2: Write `Dockerfile`**

```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY services/ingestor-hevy/pyproject.toml ./
RUN pip install --root-user-action=ignore --no-cache-dir --upgrade pip \
 && pip install --root-user-action=ignore --no-cache-dir -e .
COPY services/ingestor-hevy/app ./app
CMD ["python", "-m", "app.main"]
```

- [ ] **Step 3: Empty `__init__.py` files**

```bash
mkdir -p services/ingestor-hevy/app services/ingestor-hevy/tests services/ingestor-hevy/tests/fixtures
touch services/ingestor-hevy/app/__init__.py
touch services/ingestor-hevy/tests/__init__.py
```

- [ ] **Step 4: Create venv and verify install**

```bash
cd services/ingestor-hevy
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest --collect-only
```

Expected: "no tests collected" (we haven't written any yet).

- [ ] **Step 5: Commit**

```
git add services/ingestor-hevy/pyproject.toml services/ingestor-hevy/Dockerfile services/ingestor-hevy/app/__init__.py services/ingestor-hevy/tests/__init__.py
git commit -m "feat(ingestor-hevy): scaffold service (pyproject, Dockerfile, dirs)"
```

---

## Task 6: Hevy ingestor — config

**Files:**
- Create: `services/ingestor-hevy/app/config.py`

- [ ] **Step 1: Write `config.py`**

```python
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    hevy_api_key: str | None = None
    hevy_api_base: str = "https://api.hevyapp.com/v1"

    mongo_url: str = "mongodb://mongo:27017"
    mongo_db: str = "hack_the_body"

    # Cron-poll backstop. Default: every 6 hours.
    hevy_schedule_cron: str = "0 */6 * * *"
    # Lookback window when no cursor exists yet. None = unlimited.
    hevy_backfill_days: int | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 2: Sanity check**

```bash
cd services/ingestor-hevy && .venv/bin/python -c "from app.config import get_settings; s = get_settings(); print(s.hevy_api_base)"
```

Expected: `https://api.hevyapp.com/v1`.

- [ ] **Step 3: Commit**

```
git add services/ingestor-hevy/app/config.py
git commit -m "feat(ingestor-hevy): config (api key, schedule, backfill)"
```

---

## Task 7: Hevy ingestor — internal models

**Files:**
- Create: `services/ingestor-hevy/app/models.py`

- [ ] **Step 1: Write models**

```python
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class Workout(BaseModel):
    """Internal canonical row matching the api `workouts` collection shape."""
    model_config = ConfigDict(extra="forbid")
    ts: datetime
    activity_type: str  # always "strength" for Hevy
    duration_s: int
    distance_m: float | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    calories: int | None = None
    title: str | None = None
    exercise_count: int | None = None
    set_count: int | None = None
    updated_at: datetime
    raw: dict[str, Any]
    source: str  # "hevy"
    source_id: str  # "hevy:<uuid>"


class StrengthSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workout_source_id: str
    ts: datetime
    exercise_index: int
    exercise_title: str
    exercise_template_id: str | None = None
    set_index: int
    set_type: str
    reps: int | None = None
    weight_kg: float | None = None
    distance_m: float | None = None
    duration_s: int | None = None
    rpe: float | None = None
    superset_id: str | None = None
    notes: str | None = None
```

- [ ] **Step 2: Sanity check**

```bash
cd services/ingestor-hevy && .venv/bin/python -c "from app.models import Workout, StrengthSet; print(Workout.model_fields.keys())"
```

- [ ] **Step 3: Commit**

```
git add services/ingestor-hevy/app/models.py
git commit -m "feat(ingestor-hevy): Workout and StrengthSet models"
```

---

## Task 8: Hevy ingestor — mappers (TDD)

**Files:**
- Create: `services/ingestor-hevy/tests/fixtures/workout_strength.json`
- Create: `services/ingestor-hevy/tests/test_mappers.py`
- Create: `services/ingestor-hevy/app/mappers.py`

- [ ] **Step 1: Save fixture (a real Hevy workout shape)**

`services/ingestor-hevy/tests/fixtures/workout_strength.json`:

```json
{
  "id": "51a93a88-2f2e-42f2-9fe8-97b0791f836e",
  "title": "Bodyweight",
  "description": "",
  "start_time": "2026-05-05T18:03:37+00:00",
  "end_time": "2026-05-05T19:05:18+00:00",
  "updated_at": "2026-05-05T19:05:36.254Z",
  "created_at": "2026-05-05T19:05:36.254Z",
  "exercises": [
    {
      "index": 0,
      "title": "Incline Push Ups",
      "notes": "5th step",
      "exercise_template_id": "39C99849",
      "superset_id": null,
      "sets": [
        {"index": 0, "type": "normal", "weight_kg": null, "reps": 12,
         "distance_meters": null, "duration_seconds": null, "rpe": null},
        {"index": 1, "type": "normal", "weight_kg": null, "reps": 12,
         "distance_meters": null, "duration_seconds": null, "rpe": null}
      ]
    },
    {
      "index": 1,
      "title": "Plank",
      "notes": "",
      "exercise_template_id": "C6C9B8A0",
      "superset_id": null,
      "sets": [
        {"index": 0, "type": "normal", "weight_kg": null, "reps": null,
         "distance_meters": null, "duration_seconds": 32, "rpe": null}
      ]
    }
  ]
}
```

- [ ] **Step 2: Write failing tests**

`services/ingestor-hevy/tests/test_mappers.py`:

```python
import json
from datetime import UTC, datetime
from pathlib import Path

from app.mappers import map_strength_sets, map_workout

FIX = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text())


def test_map_workout_basics():
    raw = _load("workout_strength.json")
    w = map_workout(raw)
    assert w.source == "hevy"
    assert w.source_id == "hevy:51a93a88-2f2e-42f2-9fe8-97b0791f836e"
    assert w.activity_type == "strength"
    assert w.title == "Bodyweight"
    assert w.ts == datetime(2026, 5, 5, 18, 3, 37, tzinfo=UTC)
    assert w.duration_s == 3701  # 1h01m41s
    assert w.exercise_count == 2
    assert w.set_count == 3
    assert w.distance_m is None
    assert w.calories is None
    assert w.updated_at == datetime(2026, 5, 5, 19, 5, 36, 254000, tzinfo=UTC)
    assert w.raw == raw


def test_map_strength_sets_flattens_per_set():
    raw = _load("workout_strength.json")
    sets = map_strength_sets(raw)
    assert len(sets) == 3
    assert sets[0].workout_source_id == "hevy:51a93a88-2f2e-42f2-9fe8-97b0791f836e"
    assert sets[0].exercise_index == 0
    assert sets[0].set_index == 0
    assert sets[0].exercise_title == "Incline Push Ups"
    assert sets[0].exercise_template_id == "39C99849"
    assert sets[0].reps == 12
    assert sets[0].weight_kg is None
    assert sets[0].set_type == "normal"
    assert sets[0].notes == "5th step"  # exercise note copied to set
    # Plank set: timed instead of reps
    assert sets[2].duration_s == 32
    assert sets[2].reps is None
    assert sets[2].exercise_title == "Plank"
    # ts inherited from parent start_time
    assert sets[2].ts == datetime(2026, 5, 5, 18, 3, 37, tzinfo=UTC)


def test_map_strength_sets_handles_missing_optional_fields():
    raw = {
        "id": "abc",
        "title": "T",
        "start_time": "2026-05-01T00:00:00+00:00",
        "end_time":   "2026-05-01T00:30:00+00:00",
        "updated_at": "2026-05-01T00:30:01Z",
        "exercises": [{
            "index": 0, "title": "Squat", "notes": "",
            "exercise_template_id": "X", "superset_id": "ss-1",
            "sets": [{"index": 0, "type": "warmup",
                      "weight_kg": 60.0, "reps": 5,
                      "distance_meters": None, "duration_seconds": None,
                      "rpe": 7.5}],
        }],
    }
    sets = map_strength_sets(raw)
    assert sets[0].weight_kg == 60.0
    assert sets[0].rpe == 7.5
    assert sets[0].set_type == "warmup"
    assert sets[0].superset_id == "ss-1"
    assert sets[0].notes is None  # empty string normalizes to None
```

- [ ] **Step 3: Run, expect FAIL**

```
cd services/ingestor-hevy && .venv/bin/pytest tests/test_mappers.py -v
```

- [ ] **Step 4: Implement `app/mappers.py`**

```python
from datetime import datetime
from typing import Any

from app.models import StrengthSet, Workout


def _parse_iso(s: str) -> datetime:
    # Hevy mixes "+00:00" and trailing "Z". fromisoformat handles "+00:00";
    # normalize "Z" first.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def _none_if_blank(s: str | None) -> str | None:
    if s is None or s == "":
        return None
    return s


def map_workout(raw: dict[str, Any]) -> Workout:
    start = _parse_iso(raw["start_time"])
    end = _parse_iso(raw["end_time"])
    duration_s = int((end - start).total_seconds())
    exercises = raw.get("exercises") or []
    set_count = sum(len(ex.get("sets") or []) for ex in exercises)
    return Workout(
        ts=start,
        activity_type="strength",
        duration_s=duration_s,
        title=_none_if_blank(raw.get("title")),
        exercise_count=len(exercises),
        set_count=set_count,
        updated_at=_parse_iso(raw["updated_at"]),
        raw=raw,
        source="hevy",
        source_id=f"hevy:{raw['id']}",
    )


def map_strength_sets(raw: dict[str, Any]) -> list[StrengthSet]:
    workout_source_id = f"hevy:{raw['id']}"
    ts = _parse_iso(raw["start_time"])
    out: list[StrengthSet] = []
    for ex in raw.get("exercises") or []:
        ex_index = ex["index"]
        ex_title = ex["title"]
        ex_tpl = ex.get("exercise_template_id")
        ex_notes = _none_if_blank(ex.get("notes"))
        superset_id = ex.get("superset_id")
        for s in ex.get("sets") or []:
            out.append(StrengthSet(
                workout_source_id=workout_source_id,
                ts=ts,
                exercise_index=ex_index,
                exercise_title=ex_title,
                exercise_template_id=ex_tpl,
                set_index=s["index"],
                set_type=s.get("type") or "normal",
                reps=s.get("reps"),
                weight_kg=s.get("weight_kg"),
                distance_m=s.get("distance_meters"),
                duration_s=s.get("duration_seconds"),
                rpe=s.get("rpe"),
                superset_id=superset_id,
                notes=ex_notes,
            ))
    return out
```

- [ ] **Step 5: Run, expect PASS**

```
cd services/ingestor-hevy && .venv/bin/pytest tests/test_mappers.py -v
```

- [ ] **Step 6: Commit**

```
git add services/ingestor-hevy/app/mappers.py services/ingestor-hevy/tests/test_mappers.py services/ingestor-hevy/tests/fixtures/workout_strength.json
git commit -m "feat(ingestor-hevy): mappers for workout summary + strength sets"
```

---

## Task 9: Hevy ingestor — repo (TDD upsert + delete cascade)

**Files:**
- Create: `services/ingestor-hevy/app/repo.py`
- Create: `services/ingestor-hevy/tests/test_repo.py`

- [ ] **Step 1: Write failing tests**

```python
# services/ingestor-hevy/tests/test_repo.py
from datetime import UTC, datetime

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.models import StrengthSet, Workout
from app.repo import HevyRepo


def _w(source_id="hevy:wk1", *, updated: datetime, sets=3) -> Workout:
    return Workout(
        ts=datetime(2026, 5, 4, 18, tzinfo=UTC),
        activity_type="strength",
        duration_s=2520,
        title="Push Day",
        exercise_count=2,
        set_count=sets,
        updated_at=updated,
        raw={"id": source_id.split(":", 1)[1]},
        source="hevy",
        source_id=source_id,
    )


def _s(source_id="hevy:wk1", *, ex_idx=0, set_idx=0, reps=10) -> StrengthSet:
    return StrengthSet(
        workout_source_id=source_id,
        ts=datetime(2026, 5, 4, 18, tzinfo=UTC),
        exercise_index=ex_idx,
        exercise_title="Push Up",
        exercise_template_id="T1",
        set_index=set_idx,
        set_type="normal",
        reps=reps,
    )


@pytest.fixture
async def repo():
    client = AsyncMongoMockClient()
    return HevyRepo(client["htb_test"])


async def test_first_upsert_inserts_workout_and_sets(repo):
    changed = await repo.upsert_workout_with_sets(
        _w(updated=datetime(2026, 5, 4, 19, tzinfo=UTC)),
        [_s(set_idx=0), _s(set_idx=1)],
    )
    assert changed is True
    assert await repo.db["workouts"].count_documents({"source_id": "hevy:wk1"}) == 1
    assert await repo.db["strength_sets"].count_documents({"workout_source_id": "hevy:wk1"}) == 2


async def test_second_upsert_same_updated_at_is_noop(repo):
    t = datetime(2026, 5, 4, 19, tzinfo=UTC)
    await repo.upsert_workout_with_sets(_w(updated=t), [_s()])
    changed = await repo.upsert_workout_with_sets(_w(updated=t), [_s(reps=999)])
    assert changed is False
    # Original sets preserved (no overwrite to reps=999)
    s = await repo.db["strength_sets"].find_one({"workout_source_id": "hevy:wk1"})
    assert s["reps"] == 10


async def test_newer_updated_at_replaces_workout_and_sets(repo):
    t1 = datetime(2026, 5, 4, 19, tzinfo=UTC)
    t2 = datetime(2026, 5, 4, 20, tzinfo=UTC)
    await repo.upsert_workout_with_sets(_w(updated=t1), [_s(set_idx=0), _s(set_idx=1)])
    changed = await repo.upsert_workout_with_sets(
        _w(updated=t2), [_s(set_idx=0, reps=999)],
    )
    assert changed is True
    # Old sets replaced — only one set now, with new reps value
    rows = [d async for d in repo.db["strength_sets"].find({"workout_source_id": "hevy:wk1"})]
    assert len(rows) == 1
    assert rows[0]["reps"] == 999
    # Workout doc updated_at reflects t2
    w = await repo.db["workouts"].find_one({"source_id": "hevy:wk1"})
    assert w["updated_at"] == t2


async def test_delete_workout_cascades(repo):
    t = datetime(2026, 5, 4, 19, tzinfo=UTC)
    await repo.upsert_workout_with_sets(_w(updated=t), [_s(), _s(set_idx=1)])
    deleted = await repo.delete_workout("hevy:wk1")
    assert deleted is True
    assert await repo.db["workouts"].count_documents({"source_id": "hevy:wk1"}) == 0
    assert await repo.db["strength_sets"].count_documents({"workout_source_id": "hevy:wk1"}) == 0


async def test_delete_workout_missing_returns_false(repo):
    assert await repo.delete_workout("hevy:nope") is False


async def test_get_existing_returns_updated_at_or_none(repo):
    assert await repo.get_existing_updated_at("hevy:wk1") is None
    t = datetime(2026, 5, 4, 19, tzinfo=UTC)
    await repo.upsert_workout_with_sets(_w(updated=t), [])
    assert await repo.get_existing_updated_at("hevy:wk1") == t
```

(Note: file uses `pytest-asyncio` with `asyncio_mode = "auto"` so no `@pytest.mark.asyncio` needed — already in pyproject.)

- [ ] **Step 2: Run, expect FAIL**

```
cd services/ingestor-hevy && .venv/bin/pytest tests/test_repo.py -v
```

- [ ] **Step 3: Implement `app/repo.py`**

```python
from datetime import datetime

from pymongo.asynchronous.database import AsyncDatabase

from app.models import StrengthSet, Workout


class HevyRepo:
    def __init__(self, db: AsyncDatabase) -> None:
        self.db = db

    async def get_existing_updated_at(self, source_id: str) -> datetime | None:
        doc = await self.db["workouts"].find_one(
            {"source_id": source_id},
            projection={"updated_at": 1},
        )
        return doc.get("updated_at") if doc else None

    async def upsert_workout_with_sets(
        self,
        workout: Workout,
        sets: list[StrengthSet],
    ) -> bool:
        """Insert or replace a Hevy workout and its sets.

        Returns True if anything was written, False if the existing
        document's `updated_at` was equal-or-newer (no-op).
        """
        existing = await self.get_existing_updated_at(workout.source_id)
        if existing is not None and existing >= workout.updated_at:
            return False

        # Replace workout document atomically (delete + insert is risky;
        # replace_one with upsert is safe).
        await self.db["workouts"].replace_one(
            {"source_id": workout.source_id},
            workout.model_dump(),
            upsert=True,
        )
        # Replace sets: delete all children for this workout, insert new.
        await self.db["strength_sets"].delete_many(
            {"workout_source_id": workout.source_id},
        )
        if sets:
            await self.db["strength_sets"].insert_many(
                [s.model_dump() for s in sets],
            )
        return True

    async def delete_workout(self, source_id: str) -> bool:
        result = await self.db["workouts"].delete_one({"source_id": source_id})
        await self.db["strength_sets"].delete_many({"workout_source_id": source_id})
        return result.deleted_count > 0
```

- [ ] **Step 4: Run, expect PASS**

```
cd services/ingestor-hevy && .venv/bin/pytest tests/test_repo.py -v
```

- [ ] **Step 5: Commit**

```
git add services/ingestor-hevy/app/repo.py services/ingestor-hevy/tests/test_repo.py
git commit -m "feat(ingestor-hevy): repo with version-checked upsert + cascade delete"
```

---

## Task 10: Hevy ingestor — HTTP client

**Files:**
- Create: `services/ingestor-hevy/app/hevy_client.py`

- [ ] **Step 1: Write the client** (no separate test file — exercised via runner tests in Task 11 with httpx mocks)

```python
import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class HevyClient:
    """Thin wrapper over Hevy's public API.

    Auth: `api-key: <key>` header (lowercase, hyphenated — not Bearer).
    """

    def __init__(self, *, api_key: str, base_url: str = "https://api.hevyapp.com/v1",
                 timeout_s: float = 20.0) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"api-key": api_key},
            timeout=timeout_s,
        )

    def close(self) -> None:
        self._client.close()

    def list_workouts(self, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        r = self._client.get("/workouts", params={"page": page, "pageSize": page_size})
        r.raise_for_status()
        return r.json()

    def get_workout(self, workout_id: str) -> dict[str, Any]:
        r = self._client.get(f"/workouts/{workout_id}")
        r.raise_for_status()
        return r.json().get("workout", r.json())

    def fetch_events(self, since: str, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        """`since` is an ISO-8601 timestamp string. Returns `{events:[{type,id}],...}`.

        Hevy's events endpoint shape isn't 100% documented; we treat the
        response as `{events: [...], page, page_count}` and fall back to
        treating any list response under `events`/`workouts` keys.
        """
        r = self._client.get(
            "/workouts/events",
            params={"since": since, "page": page, "pageSize": page_size},
        )
        r.raise_for_status()
        return r.json()
```

- [ ] **Step 2: Sanity check syntax**

```bash
cd services/ingestor-hevy && .venv/bin/python -c "from app.hevy_client import HevyClient; print(HevyClient)"
```

- [ ] **Step 3: Commit**

```
git add services/ingestor-hevy/app/hevy_client.py
git commit -m "feat(ingestor-hevy): httpx-based hevy api client"
```

---

## Task 11: Hevy ingestor — runner (TDD event processing)

**Files:**
- Create: `services/ingestor-hevy/app/runner.py`
- Create: `services/ingestor-hevy/tests/test_runner.py`

- [ ] **Step 1: Write failing tests**

```python
# services/ingestor-hevy/tests/test_runner.py
from datetime import UTC, datetime

import pytest
from mongomock_motor import AsyncMongoMockClient

from app.repo import HevyRepo
from app.runner import process_event, run_backfill


class StubClient:
    """Stand-in HevyClient that returns prepared responses."""
    def __init__(self, workouts: dict[str, dict]):
        self.workouts = workouts
        self.calls: list[tuple[str, str]] = []

    def get_workout(self, wid: str):
        self.calls.append(("get", wid))
        return self.workouts[wid]

    def list_workouts(self, page=1, page_size=10):
        self.calls.append(("list", str(page)))
        all_workouts = list(self.workouts.values())
        start = (page - 1) * page_size
        chunk = all_workouts[start:start + page_size]
        page_count = max(1, (len(all_workouts) + page_size - 1) // page_size)
        return {"page": page, "page_count": page_count, "workouts": chunk}


def _hevy_workout(wid: str, updated_at: str, exercises: list | None = None) -> dict:
    return {
        "id": wid, "title": "Push", "description": "",
        "start_time": "2026-05-05T18:00:00+00:00",
        "end_time":   "2026-05-05T18:30:00+00:00",
        "updated_at": updated_at,
        "created_at": updated_at,
        "exercises": exercises or [{
            "index": 0, "title": "Push Up", "notes": "",
            "exercise_template_id": "T1", "superset_id": None,
            "sets": [{"index": 0, "type": "normal", "weight_kg": None, "reps": 10,
                      "distance_meters": None, "duration_seconds": None, "rpe": None}],
        }],
    }


@pytest.fixture
async def env():
    db = AsyncMongoMockClient()["htb_test"]
    repo = HevyRepo(db)
    return repo, db


async def test_process_event_created_inserts_workout(env):
    repo, db = env
    client = StubClient({"w1": _hevy_workout("w1", "2026-05-05T19:00:00+00:00")})
    result = await process_event(repo, client, event_type="workout.created", workout_id="w1")
    assert result == "inserted"
    assert await db["workouts"].count_documents({"source_id": "hevy:w1"}) == 1
    assert await db["strength_sets"].count_documents({"workout_source_id": "hevy:w1"}) == 1


async def test_process_event_updated_replaces_when_newer(env):
    repo, db = env
    client = StubClient({"w1": _hevy_workout("w1", "2026-05-05T19:00:00+00:00")})
    await process_event(repo, client, event_type="workout.created", workout_id="w1")
    # Bump updated_at and change reps
    new_workout = _hevy_workout("w1", "2026-05-05T20:00:00+00:00", exercises=[{
        "index": 0, "title": "Push Up", "notes": "",
        "exercise_template_id": "T1", "superset_id": None,
        "sets": [{"index": 0, "type": "normal", "weight_kg": None, "reps": 999,
                  "distance_meters": None, "duration_seconds": None, "rpe": None}],
    }])
    client.workouts["w1"] = new_workout
    result = await process_event(repo, client, event_type="workout.updated", workout_id="w1")
    assert result == "updated"
    s = await db["strength_sets"].find_one({"workout_source_id": "hevy:w1"})
    assert s["reps"] == 999


async def test_process_event_updated_noop_when_same(env):
    repo, db = env
    workout = _hevy_workout("w1", "2026-05-05T19:00:00+00:00")
    client = StubClient({"w1": workout})
    await process_event(repo, client, event_type="workout.created", workout_id="w1")
    result = await process_event(repo, client, event_type="workout.updated", workout_id="w1")
    assert result == "noop"


async def test_process_event_deleted_cascades(env):
    repo, db = env
    client = StubClient({"w1": _hevy_workout("w1", "2026-05-05T19:00:00+00:00")})
    await process_event(repo, client, event_type="workout.created", workout_id="w1")
    result = await process_event(repo, client, event_type="workout.deleted", workout_id="w1")
    assert result == "deleted"
    assert await db["workouts"].count_documents({"source_id": "hevy:w1"}) == 0
    assert await db["strength_sets"].count_documents({"workout_source_id": "hevy:w1"}) == 0
    # Delete should NOT call get_workout (we don't need the body to delete)
    assert ("get", "w1") not in client.calls[-1:]  # last call was the delete path


async def test_run_backfill_pages_and_inserts_all(env):
    repo, db = env
    client = StubClient({
        f"w{i}": _hevy_workout(f"w{i}", f"2026-05-0{i+1}T00:00:00+00:00")
        for i in range(1, 4)
    })
    n = await run_backfill(repo, client, page_size=2)
    assert n == 3
    assert await db["workouts"].count_documents({"source": "hevy"}) == 3
```

- [ ] **Step 2: Run, expect FAIL**

```
cd services/ingestor-hevy && .venv/bin/pytest tests/test_runner.py -v
```

- [ ] **Step 3: Implement `app/runner.py`**

```python
import logging
from typing import Literal, Protocol

from app.mappers import map_strength_sets, map_workout
from app.repo import HevyRepo

log = logging.getLogger(__name__)

EventType = Literal["workout.created", "workout.updated", "workout.deleted"]
ProcessResult = Literal["inserted", "updated", "noop", "deleted", "skipped"]


class HevyClientProto(Protocol):
    def get_workout(self, workout_id: str) -> dict: ...
    def list_workouts(self, page: int, page_size: int) -> dict: ...


async def process_event(
    repo: HevyRepo,
    client: HevyClientProto,
    *,
    event_type: EventType,
    workout_id: str,
) -> ProcessResult:
    if event_type == "workout.deleted":
        ok = await repo.delete_workout(f"hevy:{workout_id}")
        return "deleted" if ok else "skipped"

    raw = client.get_workout(workout_id)
    workout = map_workout(raw)
    sets = map_strength_sets(raw)
    existing = await repo.get_existing_updated_at(workout.source_id)
    changed = await repo.upsert_workout_with_sets(workout, sets)
    if not changed:
        return "noop"
    return "updated" if existing is not None else "inserted"


async def run_backfill(
    repo: HevyRepo,
    client: HevyClientProto,
    *,
    page_size: int = 10,
) -> int:
    """Page through Hevy's full workout list, upserting each."""
    total = 0
    page = 1
    while True:
        resp = client.list_workouts(page=page, page_size=page_size)
        workouts = resp.get("workouts") or []
        for raw in workouts:
            workout = map_workout(raw)
            sets = map_strength_sets(raw)
            if await repo.upsert_workout_with_sets(workout, sets):
                total += 1
        page_count = int(resp.get("page_count") or 1)
        if page >= page_count:
            break
        page += 1
    return total
```

- [ ] **Step 4: Run, expect PASS**

```
cd services/ingestor-hevy && .venv/bin/pytest tests/test_runner.py -v
```

- [ ] **Step 5: Commit**

```
git add services/ingestor-hevy/app/runner.py services/ingestor-hevy/tests/test_runner.py
git commit -m "feat(ingestor-hevy): event processor + backfill paginator"
```

---

## Task 12: Hevy ingestor — main entry (request poller + cron)

**Files:**
- Create: `services/ingestor-hevy/app/main.py`

- [ ] **Step 1: Write `main.py`** (mirrors `ingestor-garmin/app/main.py` shape)

```python
import asyncio
import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pymongo import AsyncMongoClient

from app.config import get_settings
from app.hevy_client import HevyClient
from app.repo import HevyRepo
from app.runner import process_event, run_backfill

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ingestor-hevy")


async def _consume_requests(db) -> list[dict]:
    """Pull and atomically claim all requested rows for source=hevy.
    Each row carries `payload.workout_id` and `payload.event`."""
    rows: list[dict] = []
    while True:
        doc = await db["ingestion_log"].find_one_and_update(
            {"source": "hevy", "status": "requested"},
            {"$set": {"status": "claimed"}},
        )
        if doc is None:
            return rows
        rows.append(doc)


async def _process_requested(settings, db) -> None:
    rows = await _consume_requests(db)
    if not rows:
        return
    if not settings.hevy_api_key:
        log.warning("hevy events queued but HEVY_API_KEY is not set; skipping")
        return
    client = HevyClient(api_key=settings.hevy_api_key, base_url=settings.hevy_api_base)
    repo = HevyRepo(db)
    started = datetime.now(UTC)
    counts = {"inserted": 0, "updated": 0, "noop": 0, "deleted": 0, "skipped": 0, "error": 0}
    for r in rows:
        wid = r["payload"]["workout_id"]
        ev = r["payload"]["event"]
        try:
            res = await process_event(repo, client, event_type=ev, workout_id=wid)
            counts[res] += 1
        except Exception:
            log.exception("hevy event %s %s failed", ev, wid)
            counts["error"] += 1
    client.close()
    await db["ingestion_log"].insert_one({
        "source": "hevy", "status": "ok", "kind": "events",
        "started_at": started, "finished_at": datetime.now(UTC),
        "counts": counts, "events_processed": len(rows),
    })
    log.info("hevy events processed: %s", counts)


async def _do_backfill(settings, db) -> None:
    if not settings.hevy_api_key:
        log.info("HEVY_API_KEY not set; backfill skipped")
        return
    client = HevyClient(api_key=settings.hevy_api_key, base_url=settings.hevy_api_base)
    repo = HevyRepo(db)
    started = datetime.now(UTC)
    try:
        n = await run_backfill(repo, client)
        await db["ingestion_log"].insert_one({
            "source": "hevy", "status": "ok", "kind": "backfill",
            "started_at": started, "finished_at": datetime.now(UTC),
            "counts": {"upserted": n},
        })
        log.info("hevy backfill upserted %d workouts", n)
    except Exception as e:
        log.exception("hevy backfill failed")
        await db["ingestion_log"].insert_one({
            "source": "hevy", "status": "error", "kind": "backfill",
            "started_at": started, "finished_at": datetime.now(UTC),
            "error": str(e),
        })
    finally:
        client.close()


async def _poll_loop(settings, db, interval_s: int = 30) -> None:
    while True:
        try:
            await _process_requested(settings, db)
        except Exception:
            log.exception("hevy poll loop error")
        await asyncio.sleep(interval_s)


async def _run() -> None:
    settings = get_settings()
    client = AsyncMongoClient(settings.mongo_url, tz_aware=True)
    db = client[settings.mongo_db]

    scheduler = AsyncIOScheduler(timezone="UTC")

    async def _scheduled() -> None:
        await _do_backfill(settings, db)

    scheduler.add_job(
        _scheduled, CronTrigger.from_crontab(settings.hevy_schedule_cron),
        id="hevy-backstop",
    )
    scheduler.start()
    log.info("hevy scheduler started cron=%s", settings.hevy_schedule_cron)

    # One run on startup (acts as initial backfill if DB empty).
    await _do_backfill(settings, db)
    await _poll_loop(settings, db)


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Sanity check (syntax)**

```bash
cd services/ingestor-hevy && .venv/bin/python -c "import app.main"
```

- [ ] **Step 3: Run all ingestor tests**

```
cd services/ingestor-hevy && .venv/bin/pytest -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```
git add services/ingestor-hevy/app/main.py
git commit -m "feat(ingestor-hevy): main entry with scheduler + ingestion_log poller"
```

---

## Task 13: Compose & CI updates

**Files:**
- Modify: `compose/docker-compose.yml`
- Modify: `compose/.env.example`
- Modify: `.github/workflows/build.yml`

- [ ] **Step 1: Inspect compose**

```
sed -n '1,80p' compose/docker-compose.yml
```

- [ ] **Step 2: Add the `ingestor-hevy` service to `compose/docker-compose.yml`**

Use the existing `ingestor-garmin` service as a template. Add (alphabetically near `ingestor-garmin`):

```yaml
  ingestor-hevy:
    image: ghcr.io/voglster/hack-the-body-ingestor-hevy:latest
    container_name: hack-the-body-ingestor-hevy
    restart: unless-stopped
    environment:
      MONGO_URL: mongodb://mongo:27017
      MONGO_DB: hack_the_body
      HEVY_API_KEY: ${HEVY_API_KEY}
      HEVY_SCHEDULE_CRON: ${HEVY_SCHEDULE_CRON:-0 */6 * * *}
      TZ: ${TZ:-America/Chicago}
    depends_on:
      - mongo
```

- [ ] **Step 3: Add `HEVY_WEBHOOK_SECRET` to `compose/.env.example`**

Below the existing `HEVY_API_KEY=` line:

```
# Bearer secret for /webhooks/hevy. Generate with: openssl rand -hex 32
# Must match the value passed to Hevy when registering the webhook.
HEVY_WEBHOOK_SECRET=
```

- [ ] **Step 4: Inspect CI workflow**

```
sed -n '1,120p' .github/workflows/build.yml
```

- [ ] **Step 5: Add a third build job** mirroring the existing `ingestor-garmin` job — same steps, just substitute names. Locate the `ingestor-garmin` job, copy it, and rename:

- job id: `build-ingestor-hevy`
- image name: `ghcr.io/voglster/hack-the-body-ingestor-hevy`
- file path: `services/ingestor-hevy/Dockerfile`

- [ ] **Step 6: Commit**

```
git add compose/docker-compose.yml compose/.env.example .github/workflows/build.yml
git commit -m "chore(deploy): wire ingestor-hevy into compose and CI"
```

---

## Task 14: Webhook registration script

**Files:**
- Create: `tools/register-hevy-webhook.sh`

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# Register (or rotate) the htb webhook with Hevy.
#
# Reads HEVY_API_KEY from env (or .env in repo root). Generates a fresh
# HEVY_WEBHOOK_SECRET if one isn't already in the .env. Posts the webhook
# config to Hevy and writes the secret back to .env on success.
#
# Run from repo root:  tools/register-hevy-webhook.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"
WEBHOOK_URL="${WEBHOOK_URL:-https://htb.home.vogelcc.com/webhooks/hevy}"

if [[ -f "$ENV_FILE" ]]; then
  set -a; source "$ENV_FILE"; set +a
fi

if [[ -z "${HEVY_API_KEY:-}" ]]; then
  echo "abort: HEVY_API_KEY not set (env or $ENV_FILE)" >&2
  exit 1
fi

if [[ -z "${HEVY_WEBHOOK_SECRET:-}" ]]; then
  HEVY_WEBHOOK_SECRET="$(openssl rand -hex 32)"
  echo "generated new HEVY_WEBHOOK_SECRET"
fi

echo "registering webhook -> $WEBHOOK_URL"
http_status=$(curl -s -o /tmp/hevy-webhook.json -w "%{http_code}" \
  -X POST "https://api.hevyapp.com/v1/webhook-subscription" \
  -H "api-key: $HEVY_API_KEY" \
  -H "Content-Type: application/json" \
  -d "{\"url\":\"$WEBHOOK_URL\",\"authToken\":\"$HEVY_WEBHOOK_SECRET\"}")

if [[ "$http_status" -lt 200 || "$http_status" -ge 300 ]]; then
  echo "abort: hevy returned HTTP $http_status" >&2
  cat /tmp/hevy-webhook.json >&2 || true
  exit 1
fi

# Persist secret to .env (replace or append)
if grep -q '^HEVY_WEBHOOK_SECRET=' "$ENV_FILE" 2>/dev/null; then
  awk -v k="$HEVY_WEBHOOK_SECRET" '/^HEVY_WEBHOOK_SECRET=/ { print "HEVY_WEBHOOK_SECRET=" k; next } { print }' "$ENV_FILE" > "$ENV_FILE.new"
  mv "$ENV_FILE.new" "$ENV_FILE"
else
  echo "HEVY_WEBHOOK_SECRET=$HEVY_WEBHOOK_SECRET" >> "$ENV_FILE"
fi

echo "ok. webhook registered. response:"
cat /tmp/hevy-webhook.json
echo
echo "next: copy HEVY_WEBHOOK_SECRET to host .env and restart the API:"
echo "  ssh hd 'cd ~/compose/hack-the-body && grep HEVY_WEBHOOK_SECRET .env || echo HEVY_WEBHOOK_SECRET=$HEVY_WEBHOOK_SECRET >> .env && docker compose up -d app'"
```

- [ ] **Step 2: Make executable**

```bash
chmod +x tools/register-hevy-webhook.sh
```

- [ ] **Step 3: Commit**

```
git add tools/register-hevy-webhook.sh
git commit -m "chore(tools): script to register hevy webhook + persist secret"
```

> Note: Hevy's exact webhook-registration endpoint URL/shape may differ slightly. If `POST /v1/webhook-subscription` 404s on first run, check Hevy's API docs and adjust the path inside the script. The webhook **handler** in our API is independent of how registration is done — registration can also be a one-time manual UI step in Hevy if they expose it there.

---

## Task 15: Frontend — types and API client method

**Files:**
- Modify: `services/web/src/api/types.ts`
- Modify: `services/web/src/api/client.ts`

- [ ] **Step 1: Inspect existing types**

```
sed -n '1,80p' services/web/src/api/types.ts
```

Find the existing `Workout` type.

- [ ] **Step 2: Extend `Workout` and add `StrengthSet`, `WorkoutDetail`, `WorkoutDetailExercise`**

Append to `services/web/src/api/types.ts` (and add the optional fields to `Workout`):

```ts
// Add to existing Workout type — these come back populated for Hevy strength
// rows, undefined for cardio rows. Keep all optional for back-compat.
export interface Workout {
  // ...existing fields...
  title?: string | null;
  exercise_count?: number | null;
  set_count?: number | null;
  updated_at?: string | null;
}

export interface StrengthSetView {
  set_index: number;
  set_type: string | null;
  reps: number | null;
  weight_kg: number | null;
  distance_m: number | null;
  duration_s: number | null;
  rpe: number | null;
}

export interface WorkoutDetailExercise {
  index: number;
  title: string;
  template_id: string | null;
  notes: string | null;
  superset_id: string | null;
  sets: StrengthSetView[];
}

export interface WorkoutDetail extends Workout {
  exercises?: WorkoutDetailExercise[];
}
```

(If `Workout` is already defined, **edit it in place** to add the four new optional fields rather than redeclaring it.)

- [ ] **Step 3: Add `getWorkout` to `services/web/src/api/client.ts`**

Find the `workouts:` line. Add right after it:

```ts
  workout: (sourceId: string) =>
    get<WorkoutDetail>(`/workouts/${encodeURIComponent(sourceId)}`),
```

Add the import for `WorkoutDetail` at the top of the file alongside other type imports.

- [ ] **Step 4: Build the FE to confirm types compile**

```
cd services/web && npm run build
```

Expected: build succeeds.

- [ ] **Step 5: Commit**

```
git add services/web/src/api/types.ts services/web/src/api/client.ts
git commit -m "feat(web): types + client method for workout detail"
```

---

## Task 16: Frontend — `<WorkoutListRow>` component

**Files:**
- Create: `services/web/src/components/WorkoutListRow.tsx`

- [ ] **Step 1: Implement** (no separate test file — visual component, exercised in page-level tests later)

```tsx
import { Link } from "react-router-dom";
import type { Workout } from "../api/types";

const ICON: Record<string, string> = {
  strength: "🏋",
  treadmill: "🏃",
  running: "🏃",
  walking: "🚶",
  cycling: "🚴",
};

function fmtDuration(seconds: number): string {
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m}min`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem ? `${h}h${rem}m` : `${h}h`;
}

function fmtDistance(meters?: number | null): string | null {
  if (meters == null) return null;
  const mi = meters / 1609.344;
  return mi >= 0.1 ? `${mi.toFixed(1)}mi` : `${Math.round(meters)}m`;
}

export function WorkoutListRow({ workout }: { workout: Workout }) {
  const icon = ICON[workout.activity_type] ?? "💪";
  const isStrength = workout.activity_type === "strength";
  const title = workout.title ?? workout.activity_type;
  const dur = fmtDuration(workout.duration_s);
  const right = isStrength
    ? `${workout.exercise_count ?? 0} ex · ${workout.set_count ?? 0} sets`
    : (fmtDistance(workout.distance_m) ?? "");

  return (
    <Link
      to={`/workouts/${encodeURIComponent(workout.source_id)}`}
      className="flex items-center gap-3 px-3 py-3 rounded-xl bg-neutral-900/50 active:bg-neutral-900"
    >
      <span className="text-2xl shrink-0">{icon}</span>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium truncate">{title}</div>
        <div className="text-xs text-neutral-400">
          {dur}{right ? ` · ${right}` : ""}
        </div>
      </div>
      <span className="text-neutral-600">›</span>
    </Link>
  );
}
```

- [ ] **Step 2: Build to confirm**

```
cd services/web && npm run build
```

- [ ] **Step 3: Commit**

```
git add services/web/src/components/WorkoutListRow.tsx
git commit -m "feat(web): WorkoutListRow component"
```

---

## Task 17: Frontend — `<StrengthSetTable>` component

**Files:**
- Create: `services/web/src/components/StrengthSetTable.tsx`

- [ ] **Step 1: Implement**

```tsx
import type { WorkoutDetailExercise } from "../api/types";

export function StrengthSetTable({ exercises }: { exercises: WorkoutDetailExercise[] }) {
  return (
    <div className="flex flex-col gap-4">
      {exercises.map((ex) => (
        <div key={`${ex.index}-${ex.title}`} className="bg-neutral-900/50 rounded-xl p-3">
          <div className="flex items-baseline justify-between mb-2">
            <h3 className="text-sm font-medium">{ex.title}</h3>
            <span className="text-xs text-neutral-500">{ex.sets.length} sets</span>
          </div>
          <div className="flex flex-col gap-1">
            {ex.sets.map((s) => (
              <div key={s.set_index} className="flex items-center gap-3 text-sm font-mono">
                <span className="text-neutral-500 w-4 text-right">{s.set_index + 1}</span>
                <span className="flex-1">
                  {formatSet(s)}
                </span>
                {s.rpe != null && (
                  <span className="text-xs text-amber-300">RPE {s.rpe}</span>
                )}
              </div>
            ))}
          </div>
          {ex.notes && (
            <div className="mt-2 text-xs text-neutral-500 italic">{ex.notes}</div>
          )}
        </div>
      ))}
    </div>
  );
}

function formatSet(s: { reps: number | null; weight_kg: number | null;
                       duration_s: number | null; distance_m: number | null;
                       set_type: string | null }) {
  const parts: string[] = [];
  if (s.weight_kg != null) parts.push(`${s.weight_kg}kg`);
  if (s.reps != null) parts.push(`${s.reps} reps`);
  if (s.duration_s != null) parts.push(`${s.duration_s}s`);
  if (s.distance_m != null) parts.push(`${s.distance_m}m`);
  const body = parts.join(" × ");
  if (s.set_type && s.set_type !== "normal") {
    return `${body} (${s.set_type})`;
  }
  return body || "—";
}
```

- [ ] **Step 2: Build**

```
cd services/web && npm run build
```

- [ ] **Step 3: Commit**

```
git add services/web/src/components/StrengthSetTable.tsx
git commit -m "feat(web): StrengthSetTable component"
```

---

## Task 18: Frontend — `WorkoutList` page

**Files:**
- Create: `services/web/src/pages/WorkoutList.tsx`

- [ ] **Step 1: Implement**

```tsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Workout } from "../api/types";
import { WorkoutListRow } from "../components/WorkoutListRow";

function dayKey(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    weekday: "short", month: "short", day: "numeric",
  });
}

export function WorkoutList() {
  const [rows, setRows] = useState<Workout[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.workouts(30).then(
      (data) => { if (!cancelled) setRows(data); },
      (e) => { if (!cancelled) setError(String(e)); },
    );
    return () => { cancelled = true; };
  }, []);

  if (error) return <div className="p-4 text-rose-400">Failed to load: {error}</div>;
  if (rows === null) return <div className="p-4 text-neutral-500">Loading…</div>;
  if (rows.length === 0) {
    return <div className="p-4 text-neutral-500">No workouts in the last 30 days.</div>;
  }

  // Group by local-time day
  const grouped: Array<[string, Workout[]]> = [];
  let last: string | null = null;
  for (const w of rows) {
    const k = dayKey(w.ts);
    if (k !== last) { grouped.push([k, []]); last = k; }
    grouped[grouped.length - 1][1].push(w);
  }

  return (
    <div className="max-w-2xl mx-auto p-4 pb-24">
      <header className="mb-4 flex items-center gap-3">
        <Link to="/more" className="text-neutral-400 active:text-neutral-200">‹ Back</Link>
        <h1 className="text-lg font-semibold">Workouts</h1>
      </header>
      <div className="flex flex-col gap-4">
        {grouped.map(([day, items]) => (
          <section key={day}>
            <h2 className="text-xs uppercase tracking-wide text-neutral-500 mb-2">{day}</h2>
            <div className="flex flex-col gap-2">
              {items.map((w) => <WorkoutListRow key={w.source_id} workout={w} />)}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Build**

```
cd services/web && npm run build
```

- [ ] **Step 3: Commit**

```
git add services/web/src/pages/WorkoutList.tsx
git commit -m "feat(web): /workouts list page (day-grouped, mixed cardio + strength)"
```

---

## Task 19: Frontend — `WorkoutDetail` page

**Files:**
- Create: `services/web/src/pages/WorkoutDetail.tsx`

- [ ] **Step 1: Implement** (handles strength, treadmill-active, garmin cardio)

```tsx
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ActiveWorkout, WorkoutDetail } from "../api/types";
import { StrengthSetTable } from "../components/StrengthSetTable";
import { ActiveTreadmillView } from "../components/ActiveTreadmillView";

function fmtDateTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    weekday: "short", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit",
  });
}

export function WorkoutDetailPage() {
  const { sourceId = "" } = useParams<{ sourceId: string }>();
  const [detail, setDetail] = useState<WorkoutDetail | null>(null);
  const [active, setActive] = useState<ActiveWorkout | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.workout(sourceId), api.activeWorkout()]).then(
      ([d, a]) => {
        if (cancelled) return;
        setDetail(d);
        if (a && a.source_id === sourceId) setActive(a);
      },
      (e) => { if (!cancelled) setError(String(e)); },
    );
    return () => { cancelled = true; };
  }, [sourceId]);

  if (error) return <div className="p-4 text-rose-400">Failed to load: {error}</div>;
  if (!detail) return <div className="p-4 text-neutral-500">Loading…</div>;

  return (
    <div className="max-w-2xl mx-auto p-4 pb-24">
      <header className="mb-4">
        <Link to="/workouts" className="text-neutral-400 active:text-neutral-200">‹ Workouts</Link>
        <h1 className="text-lg font-semibold mt-1">
          {detail.title ?? detail.activity_type}
        </h1>
        <div className="text-xs text-neutral-500">
          {fmtDateTime(detail.ts)} · {Math.round(detail.duration_s / 60)}min
        </div>
      </header>

      {active ? (
        <ActiveTreadmillView active={active} />
      ) : detail.activity_type === "strength" && detail.exercises ? (
        <StrengthSetTable exercises={detail.exercises} />
      ) : (
        <CardioSummary detail={detail} />
      )}
    </div>
  );
}

function CardioSummary({ detail }: { detail: WorkoutDetail }) {
  return (
    <div className="bg-neutral-900/50 rounded-xl p-4 grid grid-cols-2 gap-3 text-sm">
      {detail.distance_m != null && (
        <Field label="Distance" value={`${(detail.distance_m / 1609.344).toFixed(2)} mi`} />
      )}
      {detail.avg_hr != null && <Field label="Avg HR" value={`${detail.avg_hr}`} />}
      {detail.max_hr != null && <Field label="Max HR" value={`${detail.max_hr}`} />}
      {detail.calories != null && <Field label="Calories" value={`${detail.calories}`} />}
      <Field label="Source" value={detail.source} />
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-neutral-500 uppercase tracking-wide">{label}</div>
      <div className="font-mono">{value}</div>
    </div>
  );
}
```

- [ ] **Step 2: Extract `ActiveTreadmillView` from existing `pages/Workout.tsx`**

The existing `pages/Workout.tsx` page renders the live treadmill UI. Refactor:
- Extract its render body into a new component `services/web/src/components/ActiveTreadmillView.tsx` taking `{ active: ActiveWorkout }` as a prop.
- Have the existing `pages/Workout.tsx` become a thin redirect — see Task 20.

If the existing `Workout.tsx` is small enough, it's also fine to duplicate its rendering logic into `ActiveTreadmillView.tsx` and replace the page entirely.

Read it first:

```
sed -n '1,200p' services/web/src/pages/Workout.tsx
```

Move the JSX into `services/web/src/components/ActiveTreadmillView.tsx`, parameterized on the active workout.

- [ ] **Step 3: Build**

```
cd services/web && npm run build
```

- [ ] **Step 4: Commit**

```
git add services/web/src/pages/WorkoutDetail.tsx services/web/src/components/ActiveTreadmillView.tsx services/web/src/pages/Workout.tsx
git commit -m "feat(web): /workouts/:sourceId detail page (strength + cardio + active treadmill)"
```

---

## Task 20: Frontend — router + ActiveWorkoutCard deep link + More tab entry

**Files:**
- Modify: `services/web/src/router.tsx`
- Modify: `services/web/src/components/ActiveWorkoutCard.tsx`
- Modify: `services/web/src/pages/Dashboard.tsx`
- Modify: `services/web/src/pages/Workout.tsx` — convert to redirect

- [ ] **Step 1: Update `router.tsx`**

```tsx
import { createBrowserRouter, Navigate } from "react-router-dom";

import { RootRedirect } from "./components/RootRedirect";
import { Dashboard } from "./pages/Dashboard";
import { Kiosk } from "./pages/Kiosk";
import { WorkoutList } from "./pages/WorkoutList";
import { WorkoutDetailPage } from "./pages/WorkoutDetail";
import { WorkoutPage } from "./pages/Workout";  // legacy redirect

export const router = createBrowserRouter([
  { path: "/", element: <RootRedirect /> },
  { path: "/kiosk", element: <Kiosk /> },
  { path: "/workouts", element: <WorkoutList /> },
  { path: "/workouts/:sourceId", element: <WorkoutDetailPage /> },
  // Legacy: /workout (singular) was the live treadmill page. Redirect to
  // the active workout if one is running, else the list.
  { path: "/workout", element: <WorkoutPage /> },
  { path: "/:tab", element: <Dashboard /> },
]);
```

- [ ] **Step 2: Convert `services/web/src/pages/Workout.tsx` to a redirect**

```tsx
import { useEffect, useState } from "react";
import { Navigate } from "react-router-dom";
import { api } from "../api/client";

export function WorkoutPage() {
  const [target, setTarget] = useState<string | null>(null);
  useEffect(() => {
    api.activeWorkout().then(
      (a) => setTarget(a ? `/workouts/${encodeURIComponent(a.source_id)}` : "/workouts"),
      () => setTarget("/workouts"),
    );
  }, []);
  if (target === null) return <div className="p-4 text-neutral-500">Loading…</div>;
  return <Navigate to={target} replace />;
}
```

(The original Workout page's render lives in `<ActiveTreadmillView>` from Task 19.)

- [ ] **Step 3: Update `ActiveWorkoutCard` to deep-link to `/workouts/:sourceId` instead of `/workout`**

Find the link/onClick that currently navigates to `/workout`:

```
grep -n "/workout" services/web/src/components/ActiveWorkoutCard.tsx
```

Change it to `/workouts/${encodeURIComponent(active.source_id)}`. Keep the rest of the card behavior.

- [ ] **Step 4: Add `Workouts` entry to the More tab**

In `services/web/src/pages/Dashboard.tsx`, find the `MoreTab` function. Locate the list of links/sections inside it. Add a `Workouts` entry **at the top of the secondary list**:

```tsx
<Link
  to="/workouts"
  className="block px-3 py-3 rounded-xl bg-neutral-900/50 active:bg-neutral-900 mb-3"
>
  <div className="flex items-center justify-between">
    <span className="font-medium">Workouts</span>
    <span className="text-neutral-600">›</span>
  </div>
  <div className="text-xs text-neutral-500">Cardio + strength history</div>
</Link>
```

(Import `Link` from `react-router-dom` at the top of `Dashboard.tsx` if not already imported.)

- [ ] **Step 5: Build + run dev server, smoke test in a browser**

```
cd services/web && npm run build
```

Then in another terminal:

```
cd services/web && npm run dev
```

Open `http://localhost:5173` (or whatever Vite reports), navigate to More → Workouts, confirm the list renders (will be empty until ingestor runs against real data).

- [ ] **Step 6: Run all FE tests**

```
cd services/web && npm test -- --run
```

- [ ] **Step 7: Commit**

```
git add services/web/src/router.tsx services/web/src/pages/Workout.tsx services/web/src/components/ActiveWorkoutCard.tsx services/web/src/pages/Dashboard.tsx
git commit -m "feat(web): /workouts routes + More-tab entry + active-workout deep link"
```

---

## Task 21: API Dockerfile — verify static FE bundle still builds

**Files:** none modified, just verification.

The API image multi-stage builds the FE. After all FE changes, do a local image build to confirm nothing is broken:

- [ ] **Step 1: Build the API image locally**

```
docker build -t hack-the-body-app:dev -f services/api/Dockerfile .
```

Expected: build succeeds, including the FE stage.

- [ ] **Step 2: Build the new ingestor image locally**

```
docker build -t hack-the-body-ingestor-hevy:dev -f services/ingestor-hevy/Dockerfile .
```

Expected: build succeeds.

No commit (verification only).

---

## Task 22: End-to-end deploy and verify on `hd`

This task is **manual / operator-driven** — final integration on the actual deployment host.

- [ ] **Step 1: Push everything**

```bash
git push origin master
```

Wait for GH Actions to build the three images and push to GHCR.

- [ ] **Step 2: Add `ingestor-hevy` to Watchtower's watch list**

```bash
ssh hd
cd ~/compose/lumbergh-cloud
# edit docker-compose.yml, append `hack-the-body-ingestor-hevy` to Watchtower's command list
docker compose up -d watchtower
```

- [ ] **Step 3: Pull `compose/docker-compose.yml` updates onto the host**

```bash
ssh hd "cd ~/compose/hack-the-body && curl -sSL https://raw.githubusercontent.com/voglster/hack-the-body/main/compose/docker-compose.yml -o docker-compose.yml && docker compose pull && docker compose up -d"
```

(Or copy the file across however you usually do it.)

- [ ] **Step 4: Register webhook**

```bash
tools/register-hevy-webhook.sh
```

This generates `HEVY_WEBHOOK_SECRET` in local `.env`, registers the webhook with Hevy, and prints the SSH one-liner to copy the secret to `hd:~/compose/hack-the-body/.env` and restart the API.

Run that one-liner.

- [ ] **Step 5: Verify backfill ran**

```bash
ssh hd "docker logs hack-the-body-ingestor-hevy --tail 30"
```

Look for `hevy backfill upserted N workouts`.

- [ ] **Step 6: Smoke-test webhook**

Log a one-set test workout in Hevy. Within ~30s, check:

```bash
ssh hd "docker logs hack-the-body-ingestor-hevy --tail 10"
```

Expect: a `hevy events processed: {'inserted': 1, ...}` line.

- [ ] **Step 7: Browser check**

Open `https://htb.home.vogelcc.com/more`, tap **Workouts**, confirm the test workout shows. Tap into it, confirm the set shows.

- [ ] **Step 8: Final commit if any tweaks were needed**

If any host-side fixes were needed (compose tweak, etc.), commit them.

---

## Self-Review

**Spec coverage:**
- ✅ Webhook + cron sync model → Tasks 3, 11, 12
- ✅ Webhook security (bearer secret, payload-as-trigger) → Task 3
- ✅ Strength_sets schema + indexes → Task 1
- ✅ workouts new fields → Tasks 1 (additive, no schema change needed), 7, 8
- ✅ ingestor-hevy service layout → Tasks 5–12
- ✅ API GET /workouts/{source_id} → Task 4
- ✅ Frontend list + detail + More entry → Tasks 15–20
- ✅ Treadmill folded into /workouts/:source_id → Tasks 19, 20
- ✅ Compose + CI + tools script → Tasks 13, 14
- ✅ Backfill + idempotent upsert → Tasks 9, 11

**Placeholder check:** No "TBD"/"add error handling later"/etc. Every code block is concrete.

**Type consistency:** `source_id` everywhere is `f"hevy:{id}"`. `workout_source_id` is the FK on sets (matches DB index). `WorkoutDetail`/`StrengthSetView` types match the API response shape from Task 4.

**One known fragility:** Hevy's `/workout-subscription` endpoint shape isn't 100% verified — Task 14 calls this out and the script can be tweaked at deploy time. The webhook **handler** is independent of how Hevy is told about it, so the integration works either way.
