"""Habits repos — config and daily status."""
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.models.metrics import Sleep
from app.services.coach.habits import (
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
from app.services.metrics_repo import MetricsRepo


async def test_create_and_list_habits(mock_db):
    h1 = await create_habit(mock_db, HabitConfig(
        name="bed by 10", kind="auto", resolver="bed_by_10",
    ))
    h2 = await create_habit(mock_db, HabitConfig(
        name="make the bed", kind="manual",
    ))
    rows = await list_habits(mock_db)
    names = {r["name"] for r in rows}
    # The fixture also seeds canonical habits (e.g. "Vitamins") — assert
    # presence rather than exact-equality so adding new seeds doesn't
    # break this test.
    assert "bed by 10" in names
    assert "make the bed" in names
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
    count = await mock_db["habit_status"].count_documents({
        "habit_id": h, "local_date": today.isoformat(),
    })
    assert count == 1


async def test_status_for_day_returns_none_when_unset(mock_db):
    h = await create_habit(mock_db, HabitConfig(name="x", kind="manual"))
    assert await status_for_day(mock_db, h, date(2026, 5, 10)) is None


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


async def test_bedtime_habit_cutoff_uses_lights_out_local(mock_db):
    """When lights_out_local is set to 23:00, a 22:45 sleep onset should be
    `done` (it would be `missed` under the old hardcoded 22:00 cutoff)."""
    repo = MetricsRepo(mock_db)
    chicago = ZoneInfo("America/Chicago")
    local_d = date(2026, 5, 10)
    # Set a non-default cutoff in user_profile.
    await mock_db["user_profile"].update_one(
        {"_id": "targets"},
        {"$set": {"lights_out_local": "23:00"}},
        upsert=True,
    )
    # Sleep onset at 22:45 — after old 22:00 cutoff, but before new 23:00 cutoff.
    onset_local = datetime(2026, 5, 10, 22, 45, tzinfo=chicago)
    await repo.insert_sleep(Sleep(
        ts=onset_local.astimezone(UTC),
        duration_s=27000, deep_s=3600, rem_s=5400, light_s=16000, awake_s=2000,
        score=80, source="garmin", source_id="s:lights_out_test",
    ))
    out = await RESOLVERS["bed_by_10"](mock_db, local_d, tz=chicago)
    assert out == "done"


async def test_compose_today_mixes_auto_manual_and_none(mock_db):
    chicago = ZoneInfo("America/Chicago")
    local_d = date(2026, 5, 10)
    await create_habit(mock_db, HabitConfig(
        name="bed by 10", kind="auto", resolver="bed_by_10",
    ))
    h_manual = await create_habit(mock_db, HabitConfig(
        name="make the bed", kind="manual",
    ))
    await create_habit(mock_db, HabitConfig(
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
