from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import require_api_key
from app.services.metrics_repo import MetricsRepo

router = APIRouter(prefix="/metrics", dependencies=[Depends(require_api_key)])


def _repo(request: Request) -> MetricsRepo:
    return MetricsRepo(request.app.state.db)


def _strip_id(doc: dict | None) -> dict | None:
    if doc is None:
        return None
    doc.pop("_id", None)
    return doc


@router.get("/summary")
async def summary(request: Request):
    repo = _repo(request)
    return {
        "weight": _strip_id(await repo.latest_weight()),
        "sleep": _strip_id(await repo.latest_sleep()),
        "hrv": _strip_id(await repo.latest_hrv()),
        "rhr": _strip_id(await repo.latest_rhr()),
        "body_comp": _strip_id(await repo.latest_body_comp()),
        "vo2max": _strip_id(await repo.latest_vo2max()),
        "daily_summary": _strip_id(await repo.latest_daily_summary()),
    }


_KINDS = {"weight", "sleep", "hrv", "rhr", "body_comp", "vo2max", "daily_summary", "steps_intraday"}


@router.get("/steps/today")
async def steps_today(request: Request) -> dict:
    """15-min intraday step buckets for today (UTC) with running total."""
    repo = _repo(request)
    now = datetime.now(UTC)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    rows = await repo.range_steps_intraday(start, end)
    buckets = [
        {"ts": r["ts"], "end_ts": r["end_ts"], "steps": r["steps"],
         "activity_level": r.get("activity_level")}
        for r in rows
    ]
    total = sum(b["steps"] for b in buckets)
    return {"total": total, "buckets": buckets, "as_of": now}


@router.get("/{kind}/latest")
async def latest(kind: str, request: Request):
    if kind not in _KINDS:
        raise HTTPException(status_code=404, detail=f"unknown metric: {kind}")
    repo = _repo(request)
    method = getattr(repo, f"latest_{kind}")
    doc = await method()
    if doc is None:
        raise HTTPException(status_code=404, detail="no data")
    return _strip_id(doc)


@router.get("/{kind}/range")
async def range_(
    kind: str,
    request: Request,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
):
    if kind not in _KINDS:
        raise HTTPException(status_code=404, detail=f"unknown metric: {kind}")
    repo = _repo(request)
    method_name = f"range_{kind}"
    if not hasattr(repo, method_name):
        raise HTTPException(status_code=400, detail=f"{kind} has no range endpoint")
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    rows = await getattr(repo, method_name)(start, end)
    return [_strip_id(r) for r in rows]
