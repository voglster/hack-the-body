from datetime import UTC, datetime, time, timedelta
from typing import Annotated, Any, Literal

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.auth import require_api_key
from app.routers.profile import get_user_targets
from app.services.coach import Insight, generate_insight, recent_insights
from app.services.coach_weekly import generate_weekly_review
from app.services.food_repo import FoodRepo

router = APIRouter(prefix="/coach", dependencies=[Depends(require_api_key)])


def _serialize(insight: Insight) -> dict[str, Any]:
    return {
        "id": insight.id,
        "text": insight.text,
        "model": insight.model,
        "eval_ms": insight.eval_ms,
        "total_ms": insight.total_ms,
        "generated_at": insight.generated_at,
        "context": insight.context,
        "trigger": insight.trigger,
    }


def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except (InvalidId, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid id: {s}") from e


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
        targets = await get_user_targets(db)
        result = await generate_insight(
            settings, db, food_totals=food_totals, trigger="manual",
            day_start=day_start, day_end=day_end, targets=targets,
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


# ---------- feedback ----------

class FeedbackReq(BaseModel):
    rating: Literal["up", "down"]
    note: str | None = Field(default=None, max_length=2000)


@router.post(
    "/insights/{insight_id}/feedback",
    status_code=status.HTTP_201_CREATED,
)
async def submit_feedback(
    insight_id: str, req: FeedbackReq, request: Request,
) -> dict[str, Any]:
    """Attach feedback to a specific coach insight.

    Stored in `coach_feedback` so the review skill can join feedback
    with the originating prompt context and propose targeted edits to
    SYSTEM_PROMPT. One feedback per (insight_id, rating) — submitting
    again replaces the prior one (people change their minds).
    """
    db = request.app.state.db
    oid = _oid(insight_id)
    insight = await db["coach_insights"].find_one({"_id": oid})
    if insight is None:
        raise HTTPException(status_code=404, detail="insight not found")
    doc = {
        "insight_id": oid,
        "rating": req.rating,
        "note": (req.note or "").strip() or None,
        "created_at": datetime.now(UTC),
    }
    # Replace any earlier feedback for this insight so the most recent
    # judgment wins. The skill can still see history via the audit
    # trail — prior versions are kept under `coach_feedback_history`.
    prior = await db["coach_feedback"].find_one_and_delete({"insight_id": oid})
    if prior is not None:
        prior.pop("_id", None)
        await db["coach_feedback_history"].insert_one(prior)
    res = await db["coach_feedback"].insert_one(doc)
    return {
        "id": str(res.inserted_id),
        "insight_id": insight_id,
        "rating": req.rating,
        "note": doc["note"],
        "created_at": doc["created_at"],
    }


@router.delete("/insights")
async def clear_insights(
    request: Request,
    before: Annotated[datetime | None, Query()] = None,
) -> dict[str, int]:
    """Archive (don't hard-delete) coach insights, optionally only those
    generated before `before`. Used after a prompt-tuning pass to make
    sure the LLM's `recent_coach_messages` block doesn't contain output
    from the OLD prompt (which would re-pollute the new prompt's
    behavior). Archived rows live in `coach_insights_archive` for the
    audit trail."""
    db = request.app.state.db
    query: dict[str, Any] = {}
    if before is not None:
        query["generated_at"] = {"$lt": before}
    archived_at = datetime.now(UTC)
    archived = 0
    async for ins in db["coach_insights"].find(query):
        # Carry the original _id over as `original_id` so the audit row
        # can be linked back to feedback without conflicting with the
        # archive collection's autogenerated _id.
        ins["original_id"] = ins.pop("_id", None)
        ins["archived_at"] = archived_at
        await db["coach_insights_archive"].insert_one(ins)
        archived += 1
    if archived:
        await db["coach_insights"].delete_many(query)
    return {"archived": archived}


@router.delete("/feedback")
async def clear_feedback(
    request: Request,
    before: Annotated[datetime | None, Query()] = None,
) -> dict[str, int]:
    """Archive (don't hard-delete) all feedback rows, optionally only those
    created before `before`. Used by `tools/coach_feedback.py clear` after
    a prompt-tuning pass so future complaints are about the *new* prompt,
    not the one we just fixed. Archived rows live in
    `coach_feedback_archive` for the audit trail."""
    db = request.app.state.db
    query: dict[str, Any] = {}
    if before is not None:
        query["created_at"] = {"$lt": before}
    cleared_at = datetime.now(UTC)
    archived = 0
    async for fb in db["coach_feedback"].find(query):
        fb.pop("_id", None)
        fb["cleared_at"] = cleared_at
        await db["coach_feedback_archive"].insert_one(fb)
        archived += 1
    if archived:
        await db["coach_feedback"].delete_many(query)
    return {"archived": archived}


@router.get("/feedback")
async def list_feedback(
    request: Request,
    since: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, Any]]:
    """Feedback joined with the originating insight text + context. The
    review skill consumes this to spot recurring complaints (e.g. "told
    me I fasted 3 times this week") and propose prompt edits."""
    db = request.app.state.db
    query: dict[str, Any] = {}
    if since is not None:
        query["created_at"] = {"$gte": since}
    cur = db["coach_feedback"].find(query).sort("created_at", -1).limit(limit)
    out: list[dict[str, Any]] = []
    async for fb in cur:
        insight = await db["coach_insights"].find_one({"_id": fb["insight_id"]})
        out.append({
            "id": str(fb["_id"]),
            "rating": fb["rating"],
            "note": fb.get("note"),
            "created_at": fb["created_at"],
            "insight": {
                "id": str(fb["insight_id"]),
                "text": insight.get("text") if insight else None,
                "trigger": insight.get("trigger") if insight else None,
                "generated_at": insight.get("generated_at") if insight else None,
                "context": insight.get("context") if insight else None,
                "model": insight.get("model") if insight else None,
                # Full prompt inputs so the review tool can audit what the
                # model actually saw when it produced the bad output.
                "food_totals": insight.get("food_totals") if insight else None,
                "history_snapshot": insight.get("history_snapshot") if insight else None,
                "prompt": insight.get("prompt") if insight else None,
                "system_prompt": insight.get("system_prompt") if insight else None,
            } if insight else {"id": str(fb["insight_id"]), "missing": True},
        })
    return out


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
