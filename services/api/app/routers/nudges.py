"""Prescriptive nudges HTTP surface.

GET /nudges            → currently-firing nudges for the local 'today'
POST /nudges/dismiss   → suppress a nudge for the rest of today (or until ts)
"""
from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from app.auth import require_api_key
from app.services.nudge_dismissals import get_active_dismissals, record_dismissal
from app.services.nudges import build_context, evaluate_all

router = APIRouter(prefix="/nudges", dependencies=[Depends(require_api_key)])


@router.get("")
async def get_nudges(request: Request) -> dict:
    db = request.app.state.db
    now_utc = datetime.now(UTC)
    ctx = await build_context(db, now_utc=now_utc)
    dismissed = await get_active_dismissals(db, now_utc=now_utc)
    fired = evaluate_all(ctx, dismissed_ids=dismissed)
    return {
        "nudges": [asdict(n) for n in fired],
        "generated_at": now_utc.isoformat(),
    }


class DismissReq(BaseModel):
    nudge_id: str = Field(min_length=1, max_length=64)
    until: str


@router.post("/dismiss")
async def dismiss_nudge(req: DismissReq, request: Request) -> dict:
    db = request.app.state.db
    await record_dismissal(db, nudge_id=req.nudge_id, until=req.until)
    return {"ok": True}
