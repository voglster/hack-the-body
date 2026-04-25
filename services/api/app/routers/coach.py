from datetime import UTC, datetime, time, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import require_api_key
from app.services.coach import Insight, generate_insight, recent_insights
from app.services.food_repo import FoodRepo

router = APIRouter(prefix="/coach", dependencies=[Depends(require_api_key)])


def _serialize(insight: Insight) -> dict[str, Any]:
    return {
        "text": insight.text,
        "model": insight.model,
        "eval_ms": insight.eval_ms,
        "total_ms": insight.total_ms,
        "generated_at": insight.generated_at,
        "context": insight.context,
        "trigger": insight.trigger,
    }


async def _today_food_totals(food_repo: FoodRepo) -> dict[str, Any]:
    now = datetime.now(UTC)
    start = datetime.combine(now.date(), time.min, tzinfo=UTC)
    end = start + timedelta(days=1)
    _ = end  # reserved for future range queries
    entries = await food_repo.list_entries_for_day(start)
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
    """Generate, persist, and return a fresh coaching insight."""
    settings = request.app.state.settings
    db = request.app.state.db
    foods = FoodRepo(db)
    try:
        food_totals = await _today_food_totals(foods)
        result = await generate_insight(
            settings, db, food_totals=food_totals, trigger="manual",
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"coach LLM unavailable: {type(e).__name__}: {e}",
        ) from e
    return _serialize(result)


@router.get("/recent")
async def recent(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
) -> list[dict[str, Any]]:
    return await recent_insights(request.app.state.db, limit=limit)
