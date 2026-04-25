from datetime import UTC, datetime, time, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from app.auth import require_api_key
from app.services.coach import Insight, generate_insight
from app.services.food_repo import FoodRepo
from app.services.metrics_repo import MetricsRepo

router = APIRouter(prefix="/coach", dependencies=[Depends(require_api_key)])


def _serialize(insight: Insight) -> dict[str, Any]:
    return {
        "text": insight.text,
        "model": insight.model,
        "eval_ms": insight.eval_ms,
        "total_ms": insight.total_ms,
        "generated_at": insight.generated_at,
        "context": insight.context,
    }


async def _today_food_totals(food_repo: FoodRepo) -> dict[str, Any]:
    now = datetime.now(UTC)
    start = datetime.combine(now.date(), time.min, tzinfo=UTC)
    end = start + timedelta(days=1)
    entries = await food_repo.list_entries_for_day(start)  # uses entry's day
    _ = end  # reserved for future range queries
    totals = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    for e in entries:
        m = e.get("macros") or {}
        for k in totals:
            v = m.get(k)
            if v is not None:
                totals[k] += float(v)
    return {k: round(v, 1) for k, v in totals.items()} | {"entries": len(entries)}


@router.get("/insight")
async def insight(request: Request) -> dict[str, Any]:
    """Generate a fresh coaching insight based on the latest metrics + today's food."""
    settings = request.app.state.settings
    metrics = MetricsRepo(request.app.state.db)
    foods = FoodRepo(request.app.state.db)
    try:
        food_totals = await _today_food_totals(foods)
        result = await generate_insight(settings, metrics, food_totals=food_totals)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"coach LLM unavailable: {type(e).__name__}: {e}",
        ) from e
    return _serialize(result)
