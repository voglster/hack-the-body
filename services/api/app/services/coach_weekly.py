"""Weekly review — slow, deep coaching pass against a big local model.

Pulls the last 7 days of metrics, food, and previous coach insights, then
asks gpt-oss:120b (or whatever's configured) to produce a structured review:
what worked, what didn't, plan for the coming week. Persisted to
`coach_insights` with trigger='weekly' so the regular coach can reference it.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, time, timedelta
from typing import Any

import httpx
from pymongo.asynchronous.database import AsyncDatabase

from app.config import Settings
from app.services.coach import USER_PROFILE, Insight, save_insight
from app.services.food_repo import FoodRepo
from app.services.metrics_repo import MetricsRepo

logger = logging.getLogger(__name__)

WEEKLY_SYSTEM_PROMPT = (
    "You are a no-nonsense health coach reviewing your client's last 7 days. "
    "Be concrete and reference actual numbers from the data. Structure:\n"
    "1) **The week in one sentence.**\n"
    "2) **Wins** — 2-3 bullets, each with a number.\n"
    "3) **Misses** — 2-3 bullets, each with a number.\n"
    "4) **Pattern you should know** — one observation that ties the data together.\n"
    "5) **Next week's plan** — 3 specific, measurable actions for the coming 7 days.\n"
    "Total under 350 words. No pleasantries, no caveats, no 'consult a doctor' boilerplate."
)


def _trim(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    return {k: v for k, v in doc.items() if k not in {"_id", "meta", "raw"}}


def _trim_list(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_trim(r) for r in rows if r is not None]  # type: ignore[misc]


async def _meal_totals_for_day(repo: FoodRepo, day_start: datetime) -> dict[str, Any]:
    entries = await repo.list_entries_for_day(day_start)
    totals = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    for e in entries:
        m = e.get("macros") or {}
        for k in totals:
            v = m.get(k)
            if v is not None:
                totals[k] += float(v)
    return {
        "date": day_start.date().isoformat(),
        "entries": len(entries),
        **{k: round(v, 1) for k, v in totals.items()},
    }


async def gather_weekly_context(db: AsyncDatabase) -> dict[str, Any]:
    metrics = MetricsRepo(db)
    foods = FoodRepo(db)

    now = datetime.now(UTC)
    end = datetime.combine(now.date() + timedelta(days=1), time.min, tzinfo=UTC)
    start = end - timedelta(days=7)

    daily = _trim_list(await metrics.range_daily_summary(start, end))
    sleep = _trim_list(await metrics.range_sleep(start, end))
    hrv = _trim_list(await metrics.range_hrv(start, end))
    weight = _trim_list(await metrics.range_weight(start, end))

    food_days: list[dict[str, Any]] = []
    for i in range(7):
        d = datetime.combine((start + timedelta(days=i)).date(), time.min, tzinfo=UTC)
        food_days.append(await _meal_totals_for_day(foods, d))

    cur = (
        db["coach_insights"]
        .find({"generated_at": {"$gte": start}})
        .sort("generated_at", -1)
        .limit(20)
    )
    prior_insights = [
        {
            "generated_at": doc.get("generated_at"),
            "trigger": doc.get("trigger"),
            "text": doc.get("text"),
        }
        async for doc in cur
    ]

    return {
        "window_start_utc": start.isoformat(),
        "window_end_utc": end.isoformat(),
        "daily_summary": daily,
        "sleep": sleep,
        "hrv": hrv,
        "weight": weight,
        "food_by_day": food_days,
        "prior_insights": prior_insights,
    }


def _format_weekly_prompt(context: dict[str, Any]) -> str:
    return "\n".join([
        WEEKLY_SYSTEM_PROMPT,
        "",
        f"Client: {USER_PROFILE}",
        "",
        "Last 7 days of data (JSON):",
        json.dumps(context, indent=2, default=str),
    ])


async def generate_weekly_review(
    settings: Settings,
    db: AsyncDatabase,
    *,
    trigger: str = "weekly",
) -> Insight:
    context = await gather_weekly_context(db)
    prompt = _format_weekly_prompt(context)
    payload = {
        "model": settings.weekly_ollama_model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.4, "num_predict": 2000},
    }
    async with httpx.AsyncClient(timeout=settings.weekly_timeout_s) as c:
        r = await c.post(f"{settings.weekly_ollama_url}/api/generate", json=payload)
        r.raise_for_status()
        data = r.json()
    insight = Insight(
        text=(data.get("response") or "").strip(),
        model=settings.weekly_ollama_model,
        eval_ms=int(data.get("eval_duration", 0)) // 1_000_000,
        total_ms=int(data.get("total_duration", 0)) // 1_000_000,
        generated_at=datetime.now(UTC),
        context={"window": "7d", "summary_keys": sorted(context.keys())},
        trigger=trigger,
    )
    insight.id = await save_insight(db, insight)
    return insight
