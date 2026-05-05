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
    repo, _db = env
    workout = _hevy_workout("w1", "2026-05-05T19:00:00+00:00")
    client = StubClient({"w1": workout})
    await process_event(repo, client, event_type="workout.created", workout_id="w1")
    result = await process_event(repo, client, event_type="workout.updated", workout_id="w1")
    assert result == "noop"


async def test_process_event_deleted_cascades(env):
    repo, db = env
    client = StubClient({"w1": _hevy_workout("w1", "2026-05-05T19:00:00+00:00")})
    await process_event(repo, client, event_type="workout.created", workout_id="w1")
    calls_before = len(client.calls)
    result = await process_event(repo, client, event_type="workout.deleted", workout_id="w1")
    assert result == "deleted"
    assert await db["workouts"].count_documents({"source_id": "hevy:w1"}) == 0
    assert await db["strength_sets"].count_documents({"workout_source_id": "hevy:w1"}) == 0
    # Delete should NOT call get_workout (we don't need the body to delete)
    assert len(client.calls) == calls_before  # no new client calls during delete


async def test_run_backfill_pages_and_inserts_all(env):
    repo, db = env
    client = StubClient({
        f"w{i}": _hevy_workout(f"w{i}", f"2026-05-0{i+1}T00:00:00+00:00")
        for i in range(1, 4)
    })
    n = await run_backfill(repo, client, page_size=2)
    assert n == 3
    assert await db["workouts"].count_documents({"source": "hevy"}) == 3
