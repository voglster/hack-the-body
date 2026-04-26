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
    "the last message (e.g. did they actually do what you suggested?). "
    "IMPORTANT — food: when 'food_entries_today' is 0 it means nothing has "
    "been logged yet, NOT that the client hasn't eaten. Never accuse them "
    "of fasting or missing meals based on an empty log; instead, ask what "
    "they ate or note that nothing is logged for the slot. "
    "IMPORTANT — time: use 'local_now' (their wall clock) for any "
    "time-of-day reasoning, never UTC. 'local_hour' is the hour 0-23. "
    "If recent_coach_messages references food/sleep facts that contradict "
    "the current snapshot (e.g. it said 'you slept 4h' but current sleep "
    "shows 7h), trust the current snapshot — the older message is stale. "
    "IMPORTANT — tone: report numbers, do not dramatize them. NEVER use "
    "clinical or alarmist terms like 'catabolic state', 'starving', "
    "'metabolic collapse', 'crash', 'in danger', 'risk' (about the "
    "client's body), or anything implying medical emergency. The client "
    "is a healthy 240 lb adult; a 1500-calorie afternoon is not a crisis. "
    "If a number looks low, just state the number and a neutral nudge "
    "('1,200 cal so far — protein next?'). NEVER scold, lecture, or "
    "reference 'warnings' you previously gave; do not use phrases like "
    "'you ignored', 'you didn't listen', 'as I told you'. Each reply "
    "stands alone. Treat the user as an adult collaborator, not a "
    "patient who failed to comply."
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
    id: str | None = None  # populated after save_insight persists the row
    # Full inputs to the model — captured so a feedback review can answer
    # "what numbers + history was the model staring at when it wrote that?"
    # `prompt` is the literal rendered text sent to the LLM, including the
    # system prompt of the moment, so we can see which guard-rails were
    # active when a bad output happened (catalysts for prompt edits).
    food_totals: dict[str, Any] | None = None
    history_snapshot: list[dict[str, Any]] | None = None
    prompt: str | None = None
    system_prompt: str | None = None


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


_TIME_OF_DAY_BUCKETS: tuple[tuple[int, str], ...] = (
    (5, "late-night"),
    (11, "morning"),
    (14, "midday"),
    (18, "afternoon"),
    (22, "evening"),
)


def _time_of_day(hour: int) -> str:
    for cutoff, label in _TIME_OF_DAY_BUCKETS:
        if hour < cutoff:
            return label
    return "night"


async def gather_context(
    repo: MetricsRepo,
    *,
    day_start: datetime | None = None,
    day_end: datetime | None = None,
) -> dict[str, Any]:
    """Snapshot the latest data for the coach prompt.

    `day_start` / `day_end` are the UTC bounds of the user's *local* day (the
    browser computes them from its IANA tz). When omitted (e.g. a scheduled
    push) we fall back to the current UTC day, which is wrong for users not
    in UTC but better than crashing.
    """
    sleep = _strip_meta(await repo.latest_sleep())
    hrv = _strip_meta(await repo.latest_hrv())
    weight = _strip_meta(await repo.latest_weight())
    daily = _strip_meta(await repo.latest_daily_summary())

    now_utc = datetime.now(UTC)
    if day_start is None or day_end is None:
        day_start = datetime.combine(now_utc.date(), time.min, tzinfo=UTC)
        day_end = day_start + timedelta(days=1)
    intraday = await repo.range_steps_intraday(day_start, day_end)
    today_steps = sum(int(b.get("steps", 0)) for b in intraday)

    # Derive the user's local hour from the day window: midpoint of the
    # window matches their local noon, so window-start is local midnight.
    # `(now - window_start) % 24h` gives the local hour offset.
    elapsed = (now_utc - day_start).total_seconds()
    local_seconds = elapsed % 86_400
    local_hour = int(local_seconds // 3600)
    local_minute = int((local_seconds % 3600) // 60)
    local_now = f"{local_hour:02d}:{local_minute:02d}"

    return {
        "now_utc": now_utc.isoformat(timespec="minutes"),
        "local_now": local_now,
        "local_hour": local_hour,
        "time_of_day": _time_of_day(local_hour),
        "local_day_start_utc": day_start.isoformat(timespec="minutes"),
        "sleep": sleep,
        "hrv": hrv,
        "weight": weight,
        "daily_summary": daily,
        "steps_today": today_steps,
    }


async def recent_insights(
    db: AsyncDatabase,
    limit: int = RECENT_LIMIT,
    *,
    since: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return the most recent N insights ordered newest-first, trimmed for prompt size.

    When `since` is provided, only insights generated at or after that
    timestamp are returned. Callers from `/coach/insight` pass the local-day
    start so yesterday's coach messages don't bleed into today's prompt
    (a real failure mode: an "you haven't eaten yet" message from 11 PM
    yesterday makes the morning coach repeat the same accusation).
    """
    query: dict[str, Any] = {}
    if since is not None:
        query["generated_at"] = {"$gte": since}
    cur = db["coach_insights"].find(query).sort("generated_at", -1).limit(limit)
    return [
        {
            "id": str(doc["_id"]),
            "generated_at": doc.get("generated_at"),
            "text": doc.get("text"),
            "trigger": doc.get("trigger", "manual"),
        }
        async for doc in cur
    ]


async def save_insight(db: AsyncDatabase, insight: Insight) -> str:
    """Persist an insight; return its id as a string.

    The prompt inputs (`food_totals`, `history_snapshot`, `prompt`,
    `system_prompt`) are stored alongside the response so a feedback
    review can reconstruct exactly what the model saw. Without these,
    we'd be tuning the prompt blind.
    """
    doc = {
        "text": insight.text,
        "model": insight.model,
        "eval_ms": insight.eval_ms,
        "total_ms": insight.total_ms,
        "generated_at": insight.generated_at,
        "context": insight.context,
        "trigger": insight.trigger,
        "food_totals": insight.food_totals,
        "history_snapshot": insight.history_snapshot,
        "prompt": insight.prompt,
        "system_prompt": insight.system_prompt,
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
    day_start: datetime | None = None,
    day_end: datetime | None = None,
) -> Insight:
    repo = MetricsRepo(db)
    context = await gather_context(repo, day_start=day_start, day_end=day_end)
    history = await recent_insights(db, since=day_start)
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
        food_totals=food_totals,
        history_snapshot=history,
        prompt=prompt,
        system_prompt=SYSTEM_PROMPT,
    )
    insight.id = await save_insight(db, insight)
    return insight
