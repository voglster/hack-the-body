from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.auth import require_api_key

router = APIRouter(prefix="/admin", dependencies=[Depends(require_api_key)])

_KNOWN_SOURCES = {"garmin"}


_KNOWN_KINDS = {"full", "steps"}


@router.post("/ingest/{source}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_ingest(source: str, request: Request, kind: str = "full"):
    if source not in _KNOWN_SOURCES:
        raise HTTPException(status_code=404, detail=f"unknown source: {source}")
    if kind not in _KNOWN_KINDS:
        raise HTTPException(status_code=400, detail=f"unknown kind: {kind}")
    await request.app.state.db["ingestion_log"].insert_one({
        "source": source,
        "status": "requested",
        "kind": kind,
        "started_at": datetime.now(UTC),
        "requested_by": "api",
    })
    return {"accepted": True, "source": source, "kind": kind}


@router.get("/sync-status")
async def sync_status(request: Request) -> dict[str, Any]:
    """Latest-good and latest-failed sync per known source.

    The dashboard reads this to show 'last synced N min ago' and surface
    failures without exposing the full ingestion_log to the client.
    """
    db = request.app.state.db
    out: dict[str, Any] = {}
    for source in _KNOWN_SOURCES:
        latest = await db["ingestion_log"].find_one(
            {"source": source, "status": "ok"},
            sort=[("started_at", -1)],
        )
        latest_err = await db["ingestion_log"].find_one(
            {"source": source, "status": "error"},
            sort=[("started_at", -1)],
        )
        out[source] = {
            "last_ok": _strip(latest),
            "last_error": _strip(latest_err),
        }
    return out


@router.delete("/foods/cache")
async def clear_food_cache(request: Request) -> dict[str, int]:
    """Drop foods whose nutrition came from an external lookup so the
    next scan re-pulls fresh data. Manually-created foods, the built-in
    Water/Vitamins records, and anything currently referenced in a meal
    template are preserved.
    """
    db = request.app.state.db
    template_food_ids = set()
    async for t in db["meal_templates"].find({}, {"items.food_id": 1}):
        for item in t.get("items") or []:
            if item.get("food_id"):
                template_food_ids.add(item["food_id"])
    # Match the external sources we cache. Manual + builtin are kept.
    query: dict[str, Any] = {"source": {"$in": ["off", "usda_fdc"]}}
    deleted = 0
    async for f in db["foods"].find(query, {"_id": 1}):
        if str(f["_id"]) in template_food_ids:
            continue
        await db["foods"].delete_one({"_id": f["_id"]})
        deleted += 1
    return {"deleted": deleted}


def _strip(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    doc.pop("_id", None)
    return doc
