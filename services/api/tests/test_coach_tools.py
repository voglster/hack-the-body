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
