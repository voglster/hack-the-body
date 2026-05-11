"""Habits REST API."""
from __future__ import annotations

import os
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bson.errors import InvalidId
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.auth import require_api_key
from app.services.coach.habits import (
    RESOLVERS,
    HabitConfig,
    compose_today,
    create_habit,
    list_habits,
    mark_status,
    update_habit,
)

router = APIRouter(prefix="/habits", dependencies=[Depends(require_api_key)])


def _oid(s: str) -> ObjectId:
    try:
        return ObjectId(s)
    except (InvalidId, TypeError) as e:
        raise HTTPException(status_code=400, detail=f"invalid id: {s}") from e


def _resolve_tz() -> ZoneInfo:
    tz_name = os.environ.get("TZ") or "UTC"
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


class CreateHabitReq(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["auto", "manual", "none"]
    resolver: str | None = None


class PatchHabitReq(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    active: bool | None = None
    kind: Literal["auto", "manual", "none"] | None = None
    resolver: str | None = None


class StatusReq(BaseModel):
    status: Literal["done", "skipped", "missed", "unknown"]
    local_date: str | None = None  # YYYY-MM-DD; defaults to today (local tz)


@router.get("")
async def list_(request: Request) -> list[dict[str, Any]]:
    return await list_habits(request.app.state.db)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create(req: CreateHabitReq, request: Request) -> dict[str, Any]:
    if req.kind == "auto":
        if not req.resolver:
            raise HTTPException(
                status_code=400, detail="auto habits require a resolver name",
            )
        if req.resolver not in RESOLVERS:
            raise HTTPException(
                status_code=400,
                detail=f"unknown resolver {req.resolver!r}; "
                       f"available: {sorted(RESOLVERS.keys())}",
            )
    hid = await create_habit(
        request.app.state.db,
        HabitConfig(name=req.name, kind=req.kind, resolver=req.resolver),
    )
    return {"id": hid, "name": req.name, "kind": req.kind, "active": True}


@router.get("/today")
async def today(request: Request) -> list[dict[str, Any]]:
    tz = _resolve_tz()
    local_today = datetime.now(UTC).astimezone(tz).date()
    return await compose_today(request.app.state.db, local_today, tz=tz)


@router.patch("/{habit_id}")
async def patch(
    habit_id: str, req: PatchHabitReq, request: Request,
) -> dict[str, Any]:
    _oid(habit_id)
    patch_doc: dict[str, Any] = {}
    if req.name is not None:
        patch_doc["name"] = req.name
    if req.active is not None:
        patch_doc["active"] = req.active
    if req.kind is not None:
        patch_doc["kind"] = req.kind
    if req.resolver is not None:
        patch_doc["resolver"] = req.resolver
    if not patch_doc:
        raise HTTPException(status_code=400, detail="nothing to patch")
    await update_habit(request.app.state.db, habit_id, patch_doc)
    doc = await request.app.state.db["habits"].find_one({"_id": ObjectId(habit_id)})
    if doc is None:
        raise HTTPException(status_code=404, detail="habit not found")
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.post("/{habit_id}/status")
async def post_status(
    habit_id: str, req: StatusReq, request: Request,
) -> dict[str, Any]:
    _oid(habit_id)
    tz = _resolve_tz()
    if req.local_date:
        try:
            d = date.fromisoformat(req.local_date)
        except ValueError as e:
            raise HTTPException(
                status_code=400, detail=f"bad local_date: {e}",
            ) from e
    else:
        d = datetime.now(UTC).astimezone(tz).date()
    await mark_status(
        request.app.state.db, habit_id, d,
        status=req.status, source="manual",
    )
    return {"habit_id": habit_id, "local_date": d.isoformat(), "status": req.status}
