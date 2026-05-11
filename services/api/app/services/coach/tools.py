"""Coach tool registry — dispatch by name, cap result size, wrap errors.

Each tool is an async function `(db, **kwargs) -> dict`. The LLM gets
`schema_for_llm()` to call them by name with JSON args. Tool errors
return `{"error": "...", "hint": "..."}` so the model can recover.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

logger = logging.getLogger(__name__)

# 4KB hard cap on tool results so the model context stays bounded.
RESULT_BYTE_CAP = 4096


class ToolError(Exception):
    """Raise inside a tool to surface a friendly error to the model."""


REGISTRY: dict[str, dict[str, Any]] = {}


def _truncate(result: dict[str, Any]) -> dict[str, Any]:
    serialized = json.dumps(result, default=str)
    if len(serialized) <= RESULT_BYTE_CAP:
        return result
    return {
        "_truncated": True,
        "_note": (
            f"result exceeded {RESULT_BYTE_CAP}B and was truncated; "
            "narrow your query or pass a smaller window"
        ),
        "preview": serialized[: RESULT_BYTE_CAP - 200],
    }


async def dispatch(
    db: AsyncDatabase, name: str, args: dict[str, Any],
) -> dict[str, Any]:
    """Call a registered tool by name with kwargs. Errors are caught."""
    entry = REGISTRY.get(name)
    if entry is None:
        return {
            "error": f"unknown tool: {name!r}",
            "hint": f"available: {sorted(REGISTRY.keys())}",
        }
    try:
        result = await entry["fn"](db, **args)
    except ToolError as e:
        return {"error": str(e)}
    except TypeError as e:
        return {"error": f"bad arguments: {e}"}
    except Exception:
        logger.exception("tool %s crashed", name)
        return {"error": f"tool {name!r} crashed (logged server-side)"}
    return _truncate(result)


def schema_for_llm() -> list[dict[str, Any]]:
    """Return Ollama-compatible tool schemas for every registered tool."""
    return [entry["schema"] for entry in REGISTRY.values()]


# --- Tool stubs (filled in by Tasks 5-8) ---------------------------------

async def _trend(
    db: AsyncDatabase, *, metric: str, window_days: int,
) -> dict[str, Any]:
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    from app.services.coach.context import trend as _trend_helper  # noqa: PLC0415
    from app.services.metrics_repo import MetricsRepo  # noqa: PLC0415

    if metric not in {"hrv", "weight", "sleep_score", "steps"}:
        raise ToolError(f"unknown metric {metric!r}")
    repo = MetricsRepo(db)
    now = datetime.now(UTC)
    start = now - timedelta(days=window_days)
    if metric == "hrv":
        series = await repo.range_hrv(start, now)
        return _trend_helper(series, value_key="rmssd_ms")
    if metric == "weight":
        series = await repo.range_weight(start, now)
        return _trend_helper(series, value_key="kg")
    if metric == "sleep_score":
        series = await repo.range_sleep(start, now)
        return _trend_helper(series, value_key="score")
    # steps
    series = await repo.range_daily_summary(start, now)
    return _trend_helper(series, value_key="steps")

async def _compare_windows(db: AsyncDatabase, **_kwargs) -> dict[str, Any]:  # noqa: ARG001
    raise ToolError("compare_windows not implemented yet")

async def _food_history(db: AsyncDatabase, **_kwargs) -> dict[str, Any]:  # noqa: ARG001
    raise ToolError("food_history not implemented yet")

async def _recall(db: AsyncDatabase, **_kwargs) -> dict[str, Any]:  # noqa: ARG001
    return {"memories": []}  # Slice 4 wires this to a real store.


REGISTRY.update({
    "trend": {
        "fn": _trend,
        "schema": {
            "type": "function",
            "function": {
                "name": "trend",
                "description": "Summarize a metric over the last N days (avg, slope per day, first, last).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "metric": {"type": "string", "enum": ["hrv", "weight", "sleep_score", "steps"]},
                        "window_days": {"type": "integer", "minimum": 2, "maximum": 90},
                    },
                    "required": ["metric", "window_days"],
                },
            },
        },
    },
    "compare_windows": {
        "fn": _compare_windows,
        "schema": {
            "type": "function",
            "function": {
                "name": "compare_windows",
                "description": "Compare a metric's recent window to an earlier baseline window. Returns abs and pct delta.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "metric": {"type": "string", "enum": ["hrv", "weight", "sleep_score", "steps"]},
                        "recent_days": {"type": "integer", "minimum": 1, "maximum": 30},
                        "baseline_days": {"type": "integer", "minimum": 7, "maximum": 90},
                    },
                    "required": ["metric", "recent_days", "baseline_days"],
                },
            },
        },
    },
    "food_history": {
        "fn": _food_history,
        "schema": {
            "type": "function",
            "function": {
                "name": "food_history",
                "description": "Daily calorie and macro totals over a date range (UTC dates, YYYY-MM-DD).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                        "end_date": {"type": "string", "description": "YYYY-MM-DD inclusive"},
                    },
                    "required": ["start_date", "end_date"],
                },
            },
        },
    },
    "recall": {
        "fn": _recall,
        "schema": {
            "type": "function",
            "function": {
                "name": "recall",
                "description": "Recall durable facts the client has told the coach. Returns list of {key, value}.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "specific fact key, omit for all"},
                    },
                },
            },
        },
    },
})
