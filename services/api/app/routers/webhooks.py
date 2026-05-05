from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import BaseModel

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class HevyEvent(BaseModel):
    event: Literal["workout.created", "workout.updated", "workout.deleted"]
    id: str


@router.post("/hevy", status_code=204)
async def hevy_webhook(
    payload: HevyEvent,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> Response:
    expected = request.app.state.settings.hevy_webhook_secret
    if not expected:
        # Webhook explicitly disabled — refuse all traffic to be safe.
        raise HTTPException(status_code=503, detail="hevy webhook not configured")
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="unauthorized")

    # Enqueue. Don't fetch synchronously — the ingestor handles that path
    # on its poll loop, identical to /admin/ingest/garmin.
    await request.app.state.db["ingestion_log"].insert_one({
        "source": "hevy",
        "status": "requested",
        "started_at": datetime.now(UTC),
        "payload": {"workout_id": payload.id, "event": payload.event},
    })
    return Response(status_code=204)
