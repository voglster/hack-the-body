"""Habits REST API."""
from __future__ import annotations

import os
from datetime import UTC, date, datetime
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.auth import require_api_key
from app.services.coach.habits import (
    HABIT_ACTIONS,
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


async def _resolve_habit_id(db, ref: str) -> str:
    """Resolve a path param that may be an ObjectId OR a habit name.

    Names are stable across DB resets and readable in HA configs, while
    ObjectIds are convenient for programmatic callers. ObjectIds are 24
    hex chars, so they don't collide with reasonable habit names like
    "Vitamins" — if `ref` parses as an ObjectId we treat it as one;
    otherwise we look up by exact name first, then case-insensitive.
    404s if neither hits.
    """
    # Verify the row actually exists so we 404 (not 500) on a
    # well-formed but non-existent id.
    if ObjectId.is_valid(ref) and await db["habits"].find_one(
        {"_id": ObjectId(ref)},
    ) is not None:
        return ref
    doc = await db["habits"].find_one({"name": ref})
    if doc is None:
        # URL-friendly case-insensitive fallback so /habits/vitamins/status
        # also works — HA users will not match case religiously.
        doc = await db["habits"].find_one(
            {"name": {"$regex": f"^{ref}$", "$options": "i"}},
        )
    if doc is None:
        raise HTTPException(
            status_code=404, detail=f"habit not found: {ref!r}",
        )
    return str(doc["_id"])


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
    on_done_action: str | None = None


class PatchHabitReq(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    active: bool | None = None
    kind: Literal["auto", "manual", "none"] | None = None
    resolver: str | None = None
    on_done_action: str | None = None


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
    if req.on_done_action and req.on_done_action not in HABIT_ACTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown on_done_action {req.on_done_action!r}; "
                   f"available: {sorted(HABIT_ACTIONS.keys())}",
        )
    hid = await create_habit(
        request.app.state.db,
        HabitConfig(
            name=req.name, kind=req.kind, resolver=req.resolver,
            on_done_action=req.on_done_action,
        ),
    )
    return {
        "id": hid, "name": req.name, "kind": req.kind, "active": True,
        "on_done_action": req.on_done_action,
    }


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
    if req.on_done_action is not None:
        if req.on_done_action and req.on_done_action not in HABIT_ACTIONS:
            raise HTTPException(
                status_code=400,
                detail=f"unknown on_done_action {req.on_done_action!r}; "
                       f"available: {sorted(HABIT_ACTIONS.keys())}",
            )
        # Allow empty string to clear the action.
        patch_doc["on_done_action"] = req.on_done_action or None
    if not patch_doc:
        raise HTTPException(status_code=400, detail="nothing to patch")
    await update_habit(request.app.state.db, habit_id, patch_doc)
    doc = await request.app.state.db["habits"].find_one({"_id": ObjectId(habit_id)})
    if doc is None:
        raise HTTPException(status_code=404, detail="habit not found")
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.post("/{habit_id_or_name}/status")
async def post_status(
    habit_id_or_name: str, req: StatusReq, request: Request,
) -> dict[str, Any]:
    db = request.app.state.db
    # Accept either the mongo ObjectId or the habit's name so HA configs
    # can use the stable, human-readable name (`/habits/Vitamins/status`).
    habit_id = await _resolve_habit_id(db, habit_id_or_name)
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
    result = await mark_status(
        db, habit_id, d,
        status=req.status, source="manual", tz=tz,
    )
    return {
        "habit_id": habit_id,
        "habit_ref": habit_id_or_name,
        "local_date": d.isoformat(),
        "status": req.status,
        # Surface the side-effect outcome so callers (HA automation, the
        # dashboard) can show "✓ Vitamins logged" vs "already done today"
        # without an extra round-trip.
        "action": result.get("action"),
    }
