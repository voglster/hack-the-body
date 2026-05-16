"""Vitamin / supplement tracking — binary 'took today?' marker.

The 'today' endpoint returns whether anything supplement-shaped has been
logged in the current local day, plus the timestamp of the first one.

A daily push reminder fires from the scheduler if today's count is still 0
by COACH_VITAMIN_REMINDER_LOCAL.

Logging is now done via the generic habits API:
`POST /habits/{vitamins_habit_id}/status` body `{"status": "done"}`.
The vitamins habit's `on_done_action` is "log_vitamins" which creates the
meal_entry idempotently per local day — see
`app/services/coach/habits.py::_log_vitamins_action`. The dedicated
`POST /vitamins/log` endpoint was removed; using the generic habit endpoint
makes the IKEA-remote → Home Assistant integration trivial and gives any
future "habit with side-effect" the same plumbing for free.
"""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request

from app.auth import require_api_key
from app.services.food_repo import FoodRepo

router = APIRouter(prefix="/vitamins", dependencies=[Depends(require_api_key)])

VITAMINS_NAME = "Vitamins"


async def count_vitamins_today(
    repo: FoodRepo,
    start: datetime,
    end: datetime,
) -> tuple[int, datetime | None]:
    entries = await repo.list_entries_in_range(start, end)
    count = 0
    first: datetime | None = None
    for e in entries:
        if e.get("food_name") != VITAMINS_NAME:
            continue
        ts = e["ts"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        count += 1
        if first is None or ts < first:
            first = ts
    return count, first


@router.get("/today")
async def today(
    request: Request,
    start: Annotated[datetime | None, Query(description="UTC start of day window")] = None,
    end: Annotated[datetime | None, Query(description="UTC end of day window")] = None,
) -> dict[str, Any]:
    repo = FoodRepo(request.app.state.db)
    if start is None:
        now = datetime.now(UTC)
        start = datetime.combine(now.date(), time.min, tzinfo=UTC)
    if end is None:
        end = start + timedelta(days=1)
    count, first = await count_vitamins_today(repo, start, end)
    return {
        "logged": count > 0,
        "entries": count,
        "first_ts": first,
        "start": start,
        "end": end,
    }
