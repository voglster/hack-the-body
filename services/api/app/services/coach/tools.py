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
# Max date range for the food_history tool — keeps response bounded.
FOOD_HISTORY_MAX_DAYS = 30


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

async def _compare_windows(
    db: AsyncDatabase, *, metric: str, recent_days: int, baseline_days: int,
) -> dict[str, Any]:
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    from app.services.coach.context import delta as _delta_helper  # noqa: PLC0415
    from app.services.metrics_repo import MetricsRepo  # noqa: PLC0415

    if metric not in {"hrv", "weight", "sleep_score", "steps"}:
        raise ToolError(f"unknown metric {metric!r}")
    if baseline_days <= recent_days:
        raise ToolError("baseline_days must be greater than recent_days")
    repo = MetricsRepo(db)
    now = datetime.now(UTC)
    recent_start = now - timedelta(days=recent_days)
    baseline_start = now - timedelta(days=baseline_days)
    baseline_end = recent_start  # prior window ends where recent begins
    if metric == "hrv":
        recent = await repo.range_hrv(recent_start, now)
        prior = await repo.range_hrv(baseline_start, baseline_end)
        return _delta_helper(recent, prior, value_key="rmssd_ms")
    if metric == "weight":
        recent = await repo.range_weight(recent_start, now)
        prior = await repo.range_weight(baseline_start, baseline_end)
        return _delta_helper(recent, prior, value_key="kg")
    if metric == "sleep_score":
        recent = await repo.range_sleep(recent_start, now)
        prior = await repo.range_sleep(baseline_start, baseline_end)
        return _delta_helper(recent, prior, value_key="score")
    # steps
    recent = await repo.range_daily_summary(recent_start, now)
    prior = await repo.range_daily_summary(baseline_start, baseline_end)
    return _delta_helper(recent, prior, value_key="steps")

async def _food_history(
    db: AsyncDatabase, *, start_date: str, end_date: str,
) -> dict[str, Any]:
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    try:
        start = datetime.fromisoformat(start_date).replace(tzinfo=UTC)
        end = datetime.fromisoformat(end_date).replace(tzinfo=UTC)
    except ValueError as e:
        raise ToolError(f"bad date format (use YYYY-MM-DD): {e}") from e
    if end < start:
        raise ToolError("end_date must be >= start_date")
    days = (end - start).days + 1
    if days > FOOD_HISTORY_MAX_DAYS:
        raise ToolError(f"range too long; max {FOOD_HISTORY_MAX_DAYS} days")
    # Pull all entries in the range (inclusive of end day).
    end_exclusive = end + timedelta(days=1)
    cur = db["meal_entries"].find({"ts": {"$gte": start, "$lt": end_exclusive}})
    by_date: dict[str, dict[str, float]] = {}
    async for e in cur:
        d = e["ts"].astimezone(UTC).date().isoformat()
        bucket = by_date.setdefault(d, {
            "calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0,
        })
        m = e.get("macros") or {}
        for k in bucket:
            v = m.get(k)
            if v is not None:
                bucket[k] += float(v)
    out_days = [
        {"date": (start + timedelta(days=i)).date().isoformat(),
         **by_date.get((start + timedelta(days=i)).date().isoformat(), {
             "calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0,
         })}
        for i in range(days)
    ]
    return {"days": out_days}

async def _recall(db: AsyncDatabase, **_kwargs) -> dict[str, Any]:  # noqa: ARG001
    return {"memories": []}  # Slice 4 wires this to a real store.


async def _habit_status(
    db: AsyncDatabase, *, name: str, days_back: int = 7,
) -> dict[str, Any]:
    from datetime import UTC, datetime, timedelta  # noqa: PLC0415

    from app.services.coach.habits import (  # noqa: PLC0415
        get_habit_by_name,
        status_for_day,
    )

    habit = await get_habit_by_name(db, name)
    if habit is None:
        raise ToolError(f"no habit named {name!r}")
    today = datetime.now(UTC).date()
    out: list[dict[str, Any]] = []
    for i in range(days_back):
        d = today - timedelta(days=i)
        row = await status_for_day(db, habit["id"], d)
        out.append({
            "date": d.isoformat(),
            "status": row["status"] if row else "unknown",
            "source": row["source"] if row else None,
        })
    return {"name": habit["name"], "kind": habit["kind"], "history": out}


async def _mark_habit_done(
    db: AsyncDatabase, *, name: str, local_date: str | None = None,
) -> dict[str, Any]:
    from datetime import UTC, date, datetime  # noqa: PLC0415

    from app.services.coach.habits import (  # noqa: PLC0415
        get_habit_by_name,
        mark_status,
    )

    habit = await get_habit_by_name(db, name)
    if habit is None:
        raise ToolError(f"no habit named {name!r}")
    if habit["kind"] == "auto":
        raise ToolError(
            f"{name!r} is an auto habit — its status is derived from data, "
            "not toggled manually",
        )
    if local_date:
        try:
            d = date.fromisoformat(local_date)
        except ValueError as e:
            raise ToolError(f"bad local_date: {e}") from e
    else:
        d = datetime.now(UTC).date()
    await mark_status(db, habit["id"], d, status="done", source="coach")
    return {"name": habit["name"], "local_date": d.isoformat(), "status": "done"}


REGISTRY.update({
    "trend": {
        "fn": _trend,
        "schema": {
            "type": "function",
            "function": {
                "name": "trend",
                "description": (
                    "Summarize a metric over the last N days "
                    "(avg, slope per day, first, last)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "metric": {
                            "type": "string",
                            "enum": ["hrv", "weight", "sleep_score", "steps"],
                        },
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
                "description": (
                    "Compare a metric's recent window to an earlier baseline "
                    "window. Returns abs and pct delta."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "metric": {
                            "type": "string",
                            "enum": ["hrv", "weight", "sleep_score", "steps"],
                        },
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
                "description": (
                    "Daily calorie and macro totals over a date range "
                    "(UTC dates, YYYY-MM-DD)."
                ),
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
                "description": (
                    "Recall durable facts the client has told the coach. "
                    "Returns list of {key, value}."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "specific fact key, omit for all"},
                    },
                },
            },
        },
    },
    "habit_status": {
        "fn": _habit_status,
        "schema": {
            "type": "function",
            "function": {
                "name": "habit_status",
                "description": (
                    "Get the last N days of status for a named habit "
                    "(returns one entry per day, newest first)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "days_back": {
                            "type": "integer", "minimum": 1, "maximum": 30,
                        },
                    },
                    "required": ["name"],
                },
            },
        },
    },
    "mark_habit_done": {
        "fn": _mark_habit_done,
        "schema": {
            "type": "function",
            "function": {
                "name": "mark_habit_done",
                "description": (
                    "Mark a manual habit as done for today (or a specific "
                    "local_date, YYYY-MM-DD). Refuses to act on auto habits."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "local_date": {
                            "type": "string",
                            "description": "YYYY-MM-DD, omit for today",
                        },
                    },
                    "required": ["name"],
                },
            },
        },
    },
})
