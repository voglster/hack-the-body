"""Coach tool registry + per-tool unit tests."""
import json
from datetime import UTC, date, datetime, timedelta

from app.models.metrics import HRV, Weight
from app.services.coach.habits import HabitConfig, create_habit, mark_status
from app.services.coach.tools import (
    REGISTRY,
    ToolError,
    dispatch,
    schema_for_llm,
)
from app.services.metrics_repo import MetricsRepo


def test_schema_for_llm_lists_all_registered_tools():
    schemas = schema_for_llm()
    names = [s["function"]["name"] for s in schemas]
    # Slice 2 tool set:
    assert "trend" in names
    assert "compare_windows" in names
    assert "food_history" in names
    assert "recall" in names


async def test_dispatch_unknown_tool_returns_error(mock_db):
    out = await dispatch(mock_db, "no_such_tool", {})
    assert "error" in out
    assert "unknown" in out["error"].lower()


async def test_dispatch_caps_oversized_results(mock_db, monkeypatch):
    """A tool returning a huge dict gets truncated with a `_truncated` flag."""
    async def big_tool(_db, **_kwargs):
        return {"data": ["x" * 100] * 100}  # ~10KB serialized
    monkeypatch.setitem(REGISTRY, "big_tool", {
        "fn": big_tool,
        "schema": {"type": "function", "function": {"name": "big_tool", "description": "test"}},
    })
    out = await dispatch(mock_db, "big_tool", {})
    serialized = json.dumps(out)
    assert len(serialized) <= 4500  # 4KB cap + some slack for truncation marker
    assert out.get("_truncated") is True


async def test_dispatch_wraps_tool_exceptions_as_errors(mock_db, monkeypatch):
    async def boom_tool(_db, **_kwargs):
        raise ToolError("intentional explosion")
    monkeypatch.setitem(REGISTRY, "boom_tool", {
        "fn": boom_tool,
        "schema": {"type": "function", "function": {"name": "boom_tool", "description": "test"}},
    })
    out = await dispatch(mock_db, "boom_tool", {})
    assert "error" in out
    assert "intentional explosion" in out["error"]


async def test_trend_tool_returns_hrv_summary(mock_db):
    repo = MetricsRepo(mock_db)
    now = datetime.now(UTC)
    for i in range(7, 0, -1):
        await repo.insert_hrv(HRV(
            ts=now - timedelta(days=i) + timedelta(hours=1),
            rmssd_ms=50.0 + i,  # 51..57
            source="garmin", source_id=f"h:{i}",
        ))
    out = await dispatch(mock_db, "trend", {"metric": "hrv", "window_days": 7})
    assert "error" not in out, out
    assert out["count"] == 7
    assert out["avg"] is not None


async def test_trend_tool_returns_weight_summary(mock_db):
    repo = MetricsRepo(mock_db)
    now = datetime.now(UTC)
    for i in range(7, 0, -1):
        await repo.insert_weight(Weight(
            ts=now - timedelta(days=i) + timedelta(hours=1),
            kg=108.0,
            source="garmin", source_id=f"w:{i}",
        ))
    out = await dispatch(mock_db, "trend", {"metric": "weight", "window_days": 7})
    assert out["count"] == 7
    assert out["avg"] == 108.0


async def test_trend_tool_rejects_unknown_metric(mock_db):
    out = await dispatch(mock_db, "trend", {"metric": "bogus", "window_days": 7})
    assert "error" in out


async def test_compare_windows_tool_returns_delta(mock_db):
    repo = MetricsRepo(mock_db)
    now = datetime.now(UTC)
    # Last 7 days: 40, prior 30 days: 60 → recent avg lower.
    # IMPORTANT: shift by 1 hour to avoid sub-second drift between test
    # insertion and tool query (same pattern as the trend tests).
    for i in range(7, 0, -1):
        await repo.insert_hrv(HRV(
            ts=now - timedelta(days=i) + timedelta(hours=1), rmssd_ms=40.0,
            source="garmin", source_id=f"h-recent:{i}",
        ))
    for i in range(30, 7, -1):
        await repo.insert_hrv(HRV(
            ts=now - timedelta(days=i) + timedelta(hours=1), rmssd_ms=60.0,
            source="garmin", source_id=f"h-prior:{i}",
        ))
    out = await dispatch(mock_db, "compare_windows", {
        "metric": "hrv", "recent_days": 7, "baseline_days": 30,
    })
    assert "error" not in out, out
    assert out["recent_avg"] == 40.0
    assert out["prior_avg"] == 60.0
    assert out["abs"] == -20.0


async def test_food_history_tool_returns_daily_totals(mock_db):
    base = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    for day_offset, cal in enumerate([1800.0, 2000.0, 2100.0]):
        await mock_db["meal_entries"].insert_one({
            "ts": base + timedelta(days=day_offset),
            "food_name": "Test", "quantity_g": 100, "slot": "dinner",
            "macros": {"calories": cal, "protein_g": 100, "carbs_g": 200, "fat_g": 50},
        })
    out = await dispatch(mock_db, "food_history", {
        "start_date": "2026-04-26", "end_date": "2026-04-28",
    })
    assert "error" not in out, out
    assert len(out["days"]) == 3
    assert out["days"][0]["date"] == "2026-04-26"
    assert out["days"][0]["calories"] == 1800.0


async def test_food_history_tool_caps_range_at_30_days(mock_db):
    out = await dispatch(mock_db, "food_history", {
        "start_date": "2026-01-01", "end_date": "2026-04-01",  # ~90 days
    })
    assert "error" in out
    assert "30" in out["error"]


async def test_food_history_tool_handles_bad_date(mock_db):
    out = await dispatch(mock_db, "food_history", {
        "start_date": "not-a-date", "end_date": "2026-04-28",
    })
    assert "error" in out


async def test_habit_status_tool_returns_history(mock_db):
    hid = await create_habit(mock_db, HabitConfig(
        name="brush teeth", kind="manual",
    ))
    today = date(2026, 5, 10)
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
