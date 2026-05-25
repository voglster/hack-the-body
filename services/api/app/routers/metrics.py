from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.auth import require_api_key
from app.routers.profile import TARGETS_KEY
from app.services.metrics_repo import MetricsRepo
from app.services.weight_projection import MIN_DAYS_FOR_FIT, fit_decay

KG_TO_LB = 2.2046226

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


@router.get("/steps/day")
async def steps_day(
    request: Request,
    start: Annotated[datetime, Query(description="UTC start of the day window (ISO 8601)")],
    end: Annotated[datetime, Query(description="UTC end of the day window (ISO 8601)")],
) -> dict:
    """15-min intraday step buckets for an arbitrary day window.

    The caller (typically the browser) computes start/end as UTC ISO strings
    derived from local midnight, so timezone handling lives where it belongs:
    next to the user.
    """
    repo = _repo(request)
    rows = await repo.range_steps_intraday(start, end)
    buckets = [
        {"ts": r["ts"], "end_ts": r["end_ts"], "steps": r["steps"],
         "activity_level": r.get("activity_level")}
        for r in rows
    ]
    total = sum(b["steps"] for b in buckets)
    return {"total": total, "buckets": buckets, "start": start, "end": end}


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


@router.get("/weight/projection")
async def weight_projection(
    request: Request,
    days: Annotated[int, Query(ge=21, le=365)] = 120,
    goal: Annotated[float | None, Query(ge=50, le=600)] = None,
) -> dict[str, Any]:
    """Exponential-decay projection of weight at current effort.

    Returns the asymptote (plateau weight at current behavior), the
    decay constant, and — if `goal` is set OR `profile.targets.goal_weight_lb`
    is set — the projected date to reach it. Returns null fields with a
    `reason` when the fit can't be made (too few days, asymptote above
    goal, etc).
    """
    db = request.app.state.db
    repo = _repo(request)
    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    rows = await repo.range_weight(start, end)
    pts = [
        (
            r["ts"] if isinstance(r["ts"], datetime)
            else datetime.fromisoformat(str(r["ts"])),
            float(r["kg"]) * KG_TO_LB,
        )
        for r in rows
        if r.get("kg") is not None
    ]
    if goal is None:
        targets = await db["user_profile"].find_one({"_id": TARGETS_KEY})
        if targets is not None and targets.get("goal_weight_lb") is not None:
            goal = float(targets["goal_weight_lb"])

    fit = fit_decay(pts)
    if fit is None:
        span_days = (
            (pts[-1][0] - pts[0][0]).total_seconds() / 86_400
            if len(pts) >= 2 else 0
        )
        reason = (
            "insufficient_data"
            if len(pts) < 3 or span_days < MIN_DAYS_FOR_FIT
            else "no_decay"
        )
        return {
            "fit": None,
            "eta": None,
            "reason": reason,
            "n_points": len(pts),
        }
    eta_date = fit.date_for(goal) if goal is not None else None
    reason = None
    if goal is not None and eta_date is None:
        reason = "asymptote_above_goal"
    return {
        "fit": {
            "asymptote_lb": round(fit.asymptote_lb, 2),
            "decay_per_week": round(fit.decay_per_week, 4),
            "r_squared": round(fit.r_squared, 3),
            "n_points": fit.n_points,
            "fit_window_start": fit.t0.isoformat(),
            "w0_lb": round(fit.w0_lb, 2),
        },
        "eta": (
            {
                "goal_lb": goal,
                "date": eta_date.isoformat(),
            } if eta_date is not None else None
        ),
        "reason": reason,
    }


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
