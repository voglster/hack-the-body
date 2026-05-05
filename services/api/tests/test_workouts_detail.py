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


@pytest.mark.asyncio
async def test_active_route_still_works_after_dynamic_param(client):
    ac, _ = client
    r = await ac.get("/workouts/active")
    # Should be 204 (no active treadmill) or 200, never 404 routed to detail.
    assert r.status_code in (200, 204)
