"""Coach service — wraps Ollama for short, action-oriented insights.

The coach pulls the latest snapshot from Mongo (sleep / HRV / steps / today's
food) and asks the local LLM for one observation per metric plus a single
concrete action for the next few hours. Designed to be cheap (small prompt,
small response, ~2-3s end to end) so we can refresh on demand.

Bigger weekly review / plan-generation passes will live elsewhere; this
service is for the dashboard 'Coach' card only.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from typing import Any

import httpx

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
    "the next 4 hours. Keep total reply under 120 words."
)


@dataclass
class Insight:
    text: str
    model: str
    eval_ms: int
    total_ms: int
    generated_at: datetime
    context: dict[str, Any]


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
    """Build a compact JSON snapshot for the LLM prompt."""
    sleep = _strip_meta(await repo.latest_sleep())
    hrv = _strip_meta(await repo.latest_hrv())
    weight = _strip_meta(await repo.latest_weight())
    daily = _strip_meta(await repo.latest_daily_summary())

    # Today's intraday step total (UTC; that's fine for prompt purposes).
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


def _format_prompt(context: dict[str, Any], food_totals: dict[str, Any] | None) -> str:
    parts = [SYSTEM_PROMPT, "", f"Client: {USER_PROFILE}", "", "Latest data:"]
    parts.append(json.dumps(context, indent=2, default=str))
    if food_totals:
        parts.append("Today's food totals:")
        parts.append(json.dumps(food_totals, indent=2, default=str))
    return "\n".join(parts)


async def generate_insight(
    settings: Settings,
    repo: MetricsRepo,
    food_totals: dict[str, Any] | None = None,
) -> Insight:
    context = await gather_context(repo)
    prompt = _format_prompt(context, food_totals)
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
    return Insight(
        text=(data.get("response") or "").strip(),
        model=settings.ollama_model,
        eval_ms=int(data.get("eval_duration", 0)) // 1_000_000,
        total_ms=int(data.get("total_duration", 0)) // 1_000_000,
        generated_at=datetime.now(UTC),
        context=context,
    )
