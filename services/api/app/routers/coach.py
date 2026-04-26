from datetime import UTC, datetime, time, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import require_api_key
from app.services.coach import Insight, generate_insight, recent_insights
from app.services.coach_weekly import generate_weekly_review
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


def _resolve_day_window(
    start: datetime | None, end: datetime | None,
) -> tuple[datetime, datetime]:
    """Browser passes UTC bounds of the user's local day. Fall back to the
    UTC day if absent (e.g. cron-triggered notifications)."""
    if start is not None and end is not None:
        return start, end
    now = datetime.now(UTC)
    s = datetime.combine(now.date(), time.min, tzinfo=UTC)
    return s, s + timedelta(days=1)


async def _today_food_totals(
    food_repo: FoodRepo, start: datetime, end: datetime,
) -> dict[str, Any]:
    entries = await food_repo.list_entries_in_range(start, end)
    totals = {"calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}
    for e in entries:
        m = e.get("macros") or {}
        for k in totals:
            v = m.get(k)
            if v is not None:
                totals[k] += float(v)
    out = {k: round(v, 1) for k, v in totals.items()}
    out["entries"] = len(entries)
    out["food_logged_today"] = len(entries) > 0
    return out


@router.get("/insight")
async def insight(
    request: Request,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
) -> dict[str, Any]:
    """Generate, persist, and return a fresh coaching insight.

    The browser passes UTC bounds of its local day so food/steps totals
    and "recent coach messages" history are scoped correctly. Without
    this, a 9 PM Mountain user would see an empty food window because
    UTC has already rolled to tomorrow.
    """
    settings = request.app.state.settings
    db = request.app.state.db
    foods = FoodRepo(db)
    day_start, day_end = _resolve_day_window(start, end)
    try:
        food_totals = await _today_food_totals(foods, day_start, day_end)
        result = await generate_insight(
            settings, db, food_totals=food_totals, trigger="manual",
            day_start=day_start, day_end=day_end,
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
    since: Annotated[datetime | None, Query()] = None,
) -> list[dict[str, Any]]:
    return await recent_insights(request.app.state.db, limit=limit, since=since)


@router.get("/weekly")
async def weekly(request: Request) -> dict[str, Any]:
    """Run the deep weekly review against the big local model. Slow."""
    settings = request.app.state.settings
    db = request.app.state.db
    try:
        result = await generate_weekly_review(settings, db, trigger="weekly-manual")
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"weekly coach LLM unavailable: {type(e).__name__}: {e}",
        ) from e
    return _serialize(result)
