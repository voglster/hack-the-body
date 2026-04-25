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


_KINDS = {"weight", "sleep", "hrv", "rhr", "body_comp", "vo2max", "daily_summary"}


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
