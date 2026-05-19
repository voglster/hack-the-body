import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from app.auth import require_api_key
from app.routers.profile import get_user_targets
from app.services.coach import Insight, generate_insight, recent_insights
from app.services.coach.brief import KIOSK_SYSTEM_PROMPT
from app.services.coach_weekly import generate_weekly_review

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
        # Surfaced so the FE can render a "what the model saw" debug panel
        # — caught a scheduler timezone bug where calories looked wrong.
        "food_totals": insight.food_totals,
        "thread_id": insight.thread_id,
        "anchors": insight.anchors or {},
        "acked_at": insight.acked_at,
    }


def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except (InvalidId, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid id: {s}") from e


class ReplyReq(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


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
    try:
        targets = await get_user_targets(db)
        result = await generate_insight(
            settings, db, trigger="manual",
            day_start=start, day_end=end, targets=targets,
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"coach LLM unavailable: {type(e).__name__}: {e}",
        ) from e
    return _serialize(result)


_KIOSK_CACHE_TTL = timedelta(minutes=15)


def _kiosk_cache_key(start: datetime | None, end: datetime | None) -> str:
    def _norm(d: datetime | None) -> str:
        if d is None:
            return ""
        # Normalize to UTC + drop microseconds so identical logical
        # windows hit the same cache slot regardless of client format.
        if d.tzinfo is None:
            d = d.replace(tzinfo=UTC)
        return d.astimezone(UTC).replace(microsecond=0).isoformat()
    return f"{_norm(start)}|{_norm(end)}"


@router.get("/kiosk")
async def kiosk(
    request: Request,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
) -> dict[str, Any]:
    """Glance-line for the office kiosk.

    Same context-builder as /insight, but rendered through
    KIOSK_SYSTEM_PROMPT (~160 char output). Result is cached on
    app.state.kiosk_cache, keyed by local-day window, for 15 min so
    60s kiosk polling does not hammer the LLM.
    """
    settings = request.app.state.settings
    db = request.app.state.db

    cache = getattr(request.app.state, "kiosk_cache", None)
    if cache is None:
        cache = {}
        request.app.state.kiosk_cache = cache

    key = _kiosk_cache_key(start, end)
    now = datetime.now(UTC)
    hit = cache.get(key)
    if hit and (now - hit["stored_at"]) < _KIOSK_CACHE_TTL:
        return hit["payload"]

    try:
        targets = await get_user_targets(db)
        result = await generate_insight(
            settings, db, trigger="kiosk",
            day_start=start, day_end=end, targets=targets,
            system_prompt=KIOSK_SYSTEM_PROMPT,
            response_format="json",
        )
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"coach LLM unavailable: {type(e).__name__}: {e}",
        ) from e

    payload = _serialize(result)
    try:
        parsed = json.loads(result.text)
        payload["verb"] = str(parsed.get("verb") or "CLEAR").upper()
        payload["qualifier"] = str(parsed.get("qualifier") or "")
        urgency = str(parsed.get("urgency") or "clear").lower()
        if urgency not in ("clear", "action", "urgent"):
            urgency = "clear"
        payload["urgency"] = urgency
        payload["coach"] = str(parsed.get("coach") or "")
        anchors = parsed.get("anchors") or {}
        if isinstance(anchors, dict):
            payload["anchors"] = {
                str(k): str(v) for k, v in anchors.items()
                if isinstance(k, str) and isinstance(v, str)
            }
        else:
            payload["anchors"] = {}
    except (ValueError, AttributeError):
        # Defensive: if the model didn't emit valid JSON, fall back to a
        # neutral "clear" glance line with the raw text as the coach
        # sentence. Better to show *something* than to 500 the kiosk.
        payload["verb"] = "CLEAR"
        payload["qualifier"] = ""
        payload["urgency"] = "clear"
        payload["coach"] = result.text[:160]
        payload["anchors"] = {}

    # Server-side override: if findings.attention is empty, NOTHING needs
    # to happen right now — the model occasionally invents an action
    # anyway ("EAT" when calorie target isn't met yet, etc). Force CLEAR.
    findings_attention = (result.context or {}).get("attention") or []
    if not findings_attention:
        payload["verb"] = "CLEAR"
        payload["qualifier"] = ""
        payload["urgency"] = "clear"
    cache[key] = {"stored_at": now, "payload": payload}
    return payload


@router.get("/recent")
async def recent(
    request: Request,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    since: Annotated[datetime | None, Query()] = None,
) -> list[dict[str, Any]]:
    return await recent_insights(request.app.state.db, limit=limit, since=since)


@router.get("/thread/active")
async def thread_active(request: Request) -> dict[str, Any]:
    """Return the most recent non-closed coach thread with its turns.
    Used by the FE chat panel to render the conversation under today's brief.
    """
    from app.services.coach.threads import get_active_thread  # noqa: PLC0415
    db = request.app.state.db
    doc = await get_active_thread(db)
    if doc is None:
        raise HTTPException(status_code=404, detail="no active thread")
    return {
        "id": str(doc["_id"]),
        "started_at": doc["started_at"],
        "last_activity_at": doc["last_activity_at"],
        "surface": doc.get("surface", "web"),
        "turns": doc["turns"],
    }


@router.post("/thread/{thread_id}/reply")
async def thread_reply(
    thread_id: str, req: ReplyReq, request: Request,
) -> dict[str, Any]:
    """Run one user→coach turn through the chat agent loop and return
    the new coach turn (text + any tool_calls used)."""
    from app.services.coach.chat import reply as chat_reply  # noqa: PLC0415
    from app.services.coach.threads import get_thread  # noqa: PLC0415
    db = request.app.state.db
    _oid(thread_id)  # validate id shape, will 400 on bad input
    if await get_thread(db, thread_id) is None:
        raise HTTPException(status_code=404, detail="thread not found")
    settings = request.app.state.settings
    try:
        turn = await chat_reply(settings, db, thread_id, user_message=req.text)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"coach LLM unavailable: {type(e).__name__}: {e}",
        ) from e
    # Ensure timestamps are JSON-serializable.
    if isinstance(turn.get("ts"), datetime):
        turn["ts"] = turn["ts"].isoformat()
    return turn


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
