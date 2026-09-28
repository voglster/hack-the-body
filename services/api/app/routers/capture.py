"""Capture-first logging API.

See docs/superpowers/specs/2026-09-28-capture-first-logging-design.md.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from pydantic import BaseModel, Field

from app.auth import require_api_key
from app.services import capture as svc
from app.services.food_repo import FoodRepo
from app.services.voice.boundary import BoundaryUnavailable, build_transcriber
from app.services.voice.vocabulary import build_speech_context

router = APIRouter(prefix="/capture", tags=["capture"], dependencies=[Depends(require_api_key)])


class CaptureReq(BaseModel):
    text: str | None = None
    food_id: str | None = None
    quantity_g: float | None = Field(default=None, gt=0)
    template_id: str | None = None
    placeholder: bool = False
    ts: datetime | None = None
    device: str | None = None
    source: Literal["tap", "text", "voice", "button"] | None = None


async def _log_known(db, cap_id: str, req: CaptureReq, ts: datetime) -> list[str]:
    repo = FoodRepo(db)
    if req.template_id:
        tpl = await repo.get_template(req.template_id)
        if not tpl:
            raise HTTPException(status_code=404, detail="template not found")
        return [
            (
                await svc.log_food(
                    db,
                    food_id=i["food_id"],
                    quantity_g=i["quantity_g"],
                    ts=ts,
                    capture_id=cap_id,
                    template_id=req.template_id,
                )
            )["id"]
            for i in tpl["items"]
        ]
    food = await repo.get_food(req.food_id)  # type: ignore[arg-type]
    if not food:
        raise HTTPException(status_code=404, detail="food not found")
    qty = req.quantity_g or float(food.get("serving_g") or 100.0)
    return [
        (
            await svc.log_food(
                db,
                food_id=req.food_id,
                quantity_g=qty,  # type: ignore[arg-type]
                ts=ts,
                capture_id=cap_id,
            )
        )["id"]
    ]


@router.post("", status_code=201)
async def capture(req: CaptureReq, request: Request, background: BackgroundTasks) -> dict:
    db = request.app.state.db
    ts = req.ts or datetime.now(UTC)
    text = (req.text or "").strip()
    if req.food_id or req.template_id:
        cap = await svc.create_capture(
            db,
            source=req.source or "tap",
            ts=ts,
            device=req.device,
            status="resolved",
            payload={
                "food_id": req.food_id,
                "quantity_g": req.quantity_g,
                "template_id": req.template_id,
            },
        )
        try:
            ids = await _log_known(db, cap["id"], req, ts)
        except HTTPException:
            await svc.undo_capture(db, cap["id"])
            raise
        await svc.set_fields(db, cap["id"], entry_ids=ids, resolved_at=datetime.now(UTC))
    elif text:
        cap = await svc.create_capture(
            db,
            source=req.source or "text",
            ts=ts,
            device=req.device,
            status="pending",
            payload={"text": text},
        )
        background.add_task(svc.resolve_capture, request.app.state.settings, db, cap["id"])
    elif req.placeholder:
        cap = await svc.create_capture(
            db,
            source=req.source or "tap",
            ts=ts,
            device=req.device,
            status="placeholder",
            payload={},
        )
    else:
        raise HTTPException(status_code=422, detail="nothing to capture")
    return await svc.get_capture(db, cap["id"])  # type: ignore[return-value]


def _local_day_bounds(day: str | None) -> tuple[datetime, datetime]:
    tz = svc.local_tz()
    d = datetime.fromisoformat(day).date() if day else datetime.now(tz).date()
    start = datetime.combine(d, time.min, tzinfo=tz).astimezone(UTC)
    return start, start + timedelta(days=1)


@router.get("/today")
async def today(request: Request, day: Annotated[str | None, Query()] = None) -> dict:
    db = request.app.state.db
    start, end = _local_day_bounds(day)
    caps = [
        svc.capture_to_dict(c)
        async for c in db[svc.CAPTURES].find({"ts": {"$gte": start, "$lt": end}}).sort("ts", -1)
    ]
    entries = await FoodRepo(db).list_entries_in_range(start, end)
    totals = {"calories": 0.0, "protein_g": 0.0}
    for e in entries:
        for k in totals:
            totals[k] += (e.get("macros") or {}).get(k) or 0.0
    unresolved = sum(c["status"] in ("pending", "needs_confirm", "placeholder") for c in caps)
    names = {e["id"]: e for e in entries}
    for c in caps:
        c["entries"] = [names[i] for i in c.get("entry_ids", []) if i in names]
    return {
        "captures": caps,
        "totals": {k: round(v, 1) for k, v in totals.items()},
        "unresolved": unresolved,
    }


@router.get("/inbox")
async def inbox(request: Request) -> list[dict]:
    db = request.app.state.db
    since = datetime.now(UTC) - timedelta(days=3)
    cur = (
        db[svc.CAPTURES]
        .find(
            {
                "status": {"$in": ["needs_confirm", "placeholder", "failed"]},
                "ts": {"$gte": since},
            }
        )
        .sort("ts", -1)
    )
    return [svc.capture_to_dict(c) async for c in cur]


@router.get("/suggestions")
async def suggestions(request: Request, limit: int = 8) -> list[dict]:
    return await svc.suggestions(request.app.state.db, limit=limit)


class ConfirmReq(BaseModel):
    item_index: int = 0
    candidate_index: int | None = None
    use_estimate: bool = False
    skip: bool = False
    text: str | None = None


@router.post("/{capture_id}/confirm")
async def confirm(
    capture_id: str, req: ConfirmReq, request: Request, background: BackgroundTasks
) -> dict:
    """Answer a needs_confirm item, or fill a placeholder/failed capture with text."""
    db = request.app.state.db
    cap = await svc.get_capture(db, capture_id)
    if not cap:
        raise HTTPException(status_code=404, detail="capture not found")
    if req.text:
        await svc.set_fields(
            db,
            capture_id,
            status="pending",
            payload={"text": req.text.strip()},
            attempts=0,
            items=[],
            last_error=None,
        )
        background.add_task(svc.resolve_capture, request.app.state.settings, db, capture_id)
        return await svc.get_capture(db, capture_id)  # type: ignore[return-value]
    try:
        return await svc.confirm_item(
            request.app.state.settings,
            db,
            capture_id,
            req.item_index,
            candidate_index=req.candidate_index,
            use_estimate=req.use_estimate,
            skip=req.skip,
        )
    except (IndexError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/{capture_id}", status_code=204)
async def undo(capture_id: str, request: Request) -> None:
    if not await svc.undo_capture(request.app.state.db, capture_id):
        raise HTTPException(status_code=404, detail="capture not found")


@router.post("/voice", status_code=201)
async def capture_voice(
    request: Request,
    background: BackgroundTasks,
    audio: Annotated[UploadFile, File()],
    device: Annotated[str | None, Form()] = None,
) -> dict:
    """Transcribe a dictation and capture the transcript as text."""
    settings = request.app.state.settings
    db = request.app.state.db
    pcm = await audio.read()
    if len(pcm) > settings.voice_max_audio_bytes:
        raise HTTPException(status_code=413, detail="recording too large")
    try:
        transcript = await build_transcriber(settings).transcribe(
            pcm,
            await build_speech_context(db),
        )
    except BoundaryUnavailable as exc:
        raise HTTPException(status_code=503, detail="voice is unavailable") from exc
    transcript = (transcript or "").strip()
    if not transcript:
        raise HTTPException(status_code=422, detail="nothing was heard")
    cap = await svc.create_capture(
        db,
        source="voice",
        device=device,
        status="pending",
        payload={"text": transcript},
    )
    background.add_task(svc.resolve_capture, settings, db, cap["id"])
    return cap
