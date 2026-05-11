"""Coach thread repo — short-lived conversation docs with inline turns."""
from app.services.coach.threads import (
    Turn,
    append_turn,
    create_thread,
    get_active_thread,
    get_thread,
)


async def test_create_thread_writes_initial_coach_turn(mock_db):
    tid = await create_thread(
        mock_db,
        initial_turn=Turn(role="coach", text="Sleep solid. On track."),
    )
    assert tid
    doc = await mock_db["coach_threads"].find_one({"_id": __import__("bson").ObjectId(tid)})
    assert doc is not None
    assert doc["turns"][0]["role"] == "coach"
    assert doc["turns"][0]["text"] == "Sleep solid. On track."
    assert doc["surface"] == "web"
    assert doc["started_at"] is not None
    assert doc["last_activity_at"] is not None
    assert doc.get("closed_at") is None


async def test_append_turn_extends_existing_thread(mock_db):
    tid = await create_thread(
        mock_db, initial_turn=Turn(role="coach", text="hi"),
    )
    await append_turn(
        mock_db, tid, Turn(role="user", text="why is my HRV low?"),
    )
    doc = await get_thread(mock_db, tid)
    assert len(doc["turns"]) == 2
    assert doc["turns"][1]["role"] == "user"
    assert doc["turns"][1]["text"] == "why is my HRV low?"


async def test_get_active_thread_returns_most_recent_open(mock_db):
    """The active thread is the newest non-closed thread."""
    await create_thread(mock_db, initial_turn=Turn(role="coach", text="old"))
    newer = await create_thread(mock_db, initial_turn=Turn(role="coach", text="new"))
    active = await get_active_thread(mock_db)
    assert active is not None
    assert str(active["_id"]) == newer


async def test_get_active_thread_returns_none_when_no_threads(mock_db):
    assert await get_active_thread(mock_db) is None


async def test_append_turn_updates_last_activity(mock_db):
    tid = await create_thread(mock_db, initial_turn=Turn(role="coach", text="hi"))
    before = (await get_thread(mock_db, tid))["last_activity_at"]
    # Force a small clock advance
    await append_turn(mock_db, tid, Turn(role="user", text="hey"))
    after = (await get_thread(mock_db, tid))["last_activity_at"]
    assert after >= before
