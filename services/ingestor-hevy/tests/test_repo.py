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
    client = AsyncMongoMockClient(tz_aware=True)
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
