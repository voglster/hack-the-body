from datetime import datetime, timezone

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
        "started_at": datetime.now(timezone.utc),
        "requested_by": "api",
    })
    return {"accepted": True, "source": source}
