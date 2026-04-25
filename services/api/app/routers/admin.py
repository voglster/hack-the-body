from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.auth import require_api_key

router = APIRouter(prefix="/admin", dependencies=[Depends(require_api_key)])

_KNOWN_SOURCES = {"garmin"}


@router.post("/ingest/{source}", status_code=status.HTTP_202_ACCEPTED)
async def trigger_ingest(source: str, request: Request):
    if source not in _KNOWN_SOURCES:
        raise HTTPException(status_code=404, detail=f"unknown source: {source}")
    await request.app.state.db["ingestion_log"].insert_one({
        "source": source,
        "status": "requested",
        "started_at": datetime.now(UTC),
        "requested_by": "api",
    })
    return {"accepted": True, "source": source}


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


def _strip(doc: dict[str, Any] | None) -> dict[str, Any] | None:
    if doc is None:
        return None
    doc.pop("_id", None)
    return doc
