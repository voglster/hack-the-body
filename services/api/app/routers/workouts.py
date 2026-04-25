from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.auth import require_api_key

router = APIRouter(prefix="/workouts", dependencies=[Depends(require_api_key)])


@router.get("")
async def list_workouts(
    request: Request,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
):
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    cur = request.app.state.db["workouts"].find(
        {"ts": {"$gte": start, "$lte": end}}
    ).sort("ts", -1)
    rows = []
    async for d in cur:
        d.pop("_id", None)
        rows.append(d)
    return rows
