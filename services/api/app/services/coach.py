"""Coach service — wraps Ollama for short, action-oriented insights.

The coach pulls the latest snapshot from Mongo (sleep / HRV / steps / today's
food) plus the last few previous insights, and asks the local LLM for one
observation per metric plus a single concrete action for the next few hours.

Each generated insight is persisted to `coach_insights` so future prompts can
reference what was said before — that's the difference between a one-shot
chatbot and a coach with a memory.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any

import httpx
from pymongo.asynchronous.database import AsyncDatabase

from app.config import Settings
from app.services.metrics_repo import MetricsRepo

logger = logging.getLogger(__name__)

USER_PROFILE = (
    "43yo male, 6'5\", ~240lb. Goal: build calisthenics strength + cardio "
    "longevity. Lifelong runner; never barbell-lifted."
)

SYSTEM_PROMPT = (
    "You are a no-nonsense health coach speaking directly to your client. "
    "Use short sentences. Skip pleasantries. Reference actual numbers. "
    "Give exactly one observation per metric, then ONE concrete action for "
    "the next 4 hours. Keep total reply under 120 words. "
    "If 'recent_coach_messages' is provided, briefly note continuity from "
    "the last message (e.g. did they actually do what you suggested?)."
)

# How many recent insights to feed into the next prompt. More = better
# continuity, but tokens grow linearly. 5 fits in <2k tokens easily.
RECENT_LIMIT = 5


@dataclass
class Insight:
    text: str
    model: str
    eval_ms: int
    total_ms: int
    generated_at: datetime
    context: dict[str, Any]
    trigger: str = "manual"


def _strip_meta(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    """Drop fields the coach doesn't need so prompts stay tight."""
    if doc is None:
        return None
    out: dict[str, Any] = {}
    for k, v in doc.items():
        if k in {"_id", "meta", "raw"}:
            continue
        out[k] = v
    return out


async def gather_context(repo: MetricsRepo) -> dict[str, Any]:
    sleep = _strip_meta(await repo.latest_sleep())
    hrv = _strip_meta(await repo.latest_hrv())
    weight = _strip_meta(await repo.latest_weight())
    daily = _strip_meta(await repo.latest_daily_summary())

    now = datetime.now(UTC)
    start = datetime.combine(now.date(), time.min, tzinfo=UTC)
    end = start + timedelta(days=1)
    intraday = await repo.range_steps_intraday(start, end)
    today_steps = sum(int(b.get("steps", 0)) for b in intraday)

    return {
        "now_utc": now.isoformat(timespec="minutes"),
        "sleep": sleep,
        "hrv": hrv,
        "weight": weight,
        "daily_summary": daily,
        "steps_today": today_steps,
    }


async def recent_insights(db: AsyncDatabase, limit: int = RECENT_LIMIT) -> list[dict[str, Any]]:
    """Return the most recent N insights ordered newest-first, trimmed for prompt size."""
    cur = db["coach_insights"].find().sort("generated_at", -1).limit(limit)
    return [
        {
            "generated_at": doc.get("generated_at"),
            "text": doc.get("text"),
            "trigger": doc.get("trigger", "manual"),
        }
        async for doc in cur
    ]


async def save_insight(db: AsyncDatabase, insight: Insight) -> str:
    """Persist an insight; return its id as a string."""
    doc = {
        "text": insight.text,
        "model": insight.model,
        "eval_ms": insight.eval_ms,
        "total_ms": insight.total_ms,
        "generated_at": insight.generated_at,
        "context": insight.context,
        "trigger": insight.trigger,
    }
    res = await db["coach_insights"].insert_one(doc)
    return str(res.inserted_id)


def _format_prompt(
    context: dict[str, Any],
    food_totals: dict[str, Any] | None,
    history: list[dict[str, Any]],
) -> str:
    parts = [SYSTEM_PROMPT, "", f"Client: {USER_PROFILE}", "", "Latest data:"]
    parts.append(json.dumps(context, indent=2, default=str))
    if food_totals:
        parts.append("Today's food totals:")
        parts.append(json.dumps(food_totals, indent=2, default=str))
    if history:
        # Oldest first, so the latest message is right above the response.
        parts.append("Recent coach messages (oldest first):")
        for h in reversed(history):
            ts = h.get("generated_at")
            ts_s = ts.isoformat(timespec="minutes") if isinstance(ts, datetime) else str(ts)
            parts.append(f"[{h.get('trigger', 'manual')} @ {ts_s}] {h.get('text', '')}")
    return "\n".join(parts)


async def generate_insight(
    settings: Settings,
    db: AsyncDatabase,
    food_totals: dict[str, Any] | None = None,
    *,
    trigger: str = "manual",
) -> Insight:
    repo = MetricsRepo(db)
    context = await gather_context(repo)
    history = await recent_insights(db)
    prompt = _format_prompt(context, food_totals, history)
    payload = {
        "model": settings.ollama_model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {"temperature": 0.4, "num_predict": 400},
    }
    async with httpx.AsyncClient(timeout=settings.coach_timeout_s) as c:
        r = await c.post(f"{settings.ollama_url}/api/generate", json=payload)
        r.raise_for_status()
        data = r.json()
    insight = Insight(
        text=(data.get("response") or "").strip(),
        model=settings.ollama_model,
        eval_ms=int(data.get("eval_duration", 0)) // 1_000_000,
        total_ms=int(data.get("total_duration", 0)) // 1_000_000,
        generated_at=datetime.now(UTC),
        context=context,
        trigger=trigger,
    )
    await save_insight(db, insight)
    return insight
