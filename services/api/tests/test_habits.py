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
