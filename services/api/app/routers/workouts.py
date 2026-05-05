from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.auth import require_api_key
from app.services.treadmill_aggregator import get_active

router = APIRouter(prefix="/workouts", dependencies=[Depends(require_api_key)])


@router.get("")
async def list_workouts(
    request: Request,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
):
    # Side effect: ensure any finished treadmill sessions in the lookback
    # window are persisted before we list. Cheap (only scans recent samples).
    await get_active(request.app.state.db)

    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    cur = request.app.state.db["workouts"].find(
        {"ts": {"$gte": start, "$lte": end}},
    ).sort("ts", -1)
    rows = []
    async for d in cur:
        d.pop("_id", None)
        rows.append(d)
    return rows


@router.get("/active")
async def active_workout(request: Request):
    summary = await get_active(request.app.state.db)
    if summary is None or summary.status != "active":
        return Response(status_code=204)
    return summary.to_doc()


@router.get("/treadmill/samples")
async def treadmill_samples(
    request: Request,
    minutes: Annotated[int, Query(ge=1, le=24 * 60)] = 60,
):
    end = datetime.now(UTC)
    start = end - timedelta(minutes=minutes)
    cur = request.app.state.db["treadmill_samples"].find(
        {"source": "precor-csafe", "ts": {"$gte": start, "$lte": end}},
        sort=[("ts", 1)],
    )
    rows = []
    async for d in cur:
        d.pop("_id", None)
        rows.append(d)
    return rows


@router.get("/{source_id:path}")
async def get_workout(request: Request, source_id: str):
    db = request.app.state.db
    doc = await db["workouts"].find_one({"source_id": source_id})
    if doc is None:
        raise HTTPException(status_code=404, detail="workout not found")
    doc.pop("_id", None)

    if doc.get("activity_type") == "strength":
        sets_cursor = db["strength_sets"].find(
            {"workout_source_id": source_id},
        ).sort([("exercise_index", 1), ("set_index", 1)])
        exercises: list[dict] = []
        current: dict | None = None
        async for s in sets_cursor:
            s.pop("_id", None)
            if current is None or s["exercise_index"] != current["index"]:
                current = {
                    "index": s["exercise_index"],
                    "title": s["exercise_title"],
                    "template_id": s.get("exercise_template_id"),
                    "notes": s.get("notes"),
                    "superset_id": s.get("superset_id"),
                    "sets": [],
                }
                exercises.append(current)
            current["sets"].append({
                "set_index": s["set_index"],
                "set_type": s.get("set_type"),
                "reps": s.get("reps"),
                "weight_kg": s.get("weight_kg"),
                "distance_m": s.get("distance_m"),
                "duration_s": s.get("duration_s"),
                "rpe": s.get("rpe"),
            })
        doc["exercises"] = exercises

    return doc
