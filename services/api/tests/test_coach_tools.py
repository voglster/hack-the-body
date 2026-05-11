"""Coach tool registry + per-tool unit tests."""
import json

import pytest

from app.services.coach.tools import (
    REGISTRY,
    ToolError,
    dispatch,
    schema_for_llm,
)


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


from datetime import UTC, datetime, timedelta

from app.models.metrics import HRV, Weight
from app.services.metrics_repo import MetricsRepo


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
