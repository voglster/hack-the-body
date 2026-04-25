from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.auth import require_api_key
from app.services.push import (
    delete_subscription_by_endpoint,
    ensure_vapid_keys,
    save_subscription,
    send_push,
)

router = APIRouter(prefix="/push", dependencies=[Depends(require_api_key)])


class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class Subscription(BaseModel):
    endpoint: str
    keys: SubscriptionKeys
    expirationTime: float | None = None  # noqa: N815 (browser key)


@router.get("/vapid-public-key")
async def vapid_public_key(request: Request) -> dict[str, str]:
    pub, _priv = await ensure_vapid_keys(request.app.state.settings, request.app.state.db)
    return {"public_key": pub}


@router.post("/subscribe", status_code=201)
async def subscribe(sub: Subscription, request: Request) -> dict[str, Any]:
    stored = await save_subscription(request.app.state.db, sub.model_dump())
    stored.pop("_id", None)
    return stored


@router.delete("/subscribe", status_code=204)
async def unsubscribe(endpoint: str, request: Request) -> None:
    deleted = await delete_subscription_by_endpoint(request.app.state.db, endpoint)
    if deleted == 0:
        raise HTTPException(status_code=404, detail="subscription not found")


@router.post("/test")
async def test_push(request: Request) -> dict[str, int]:
    """Send a test notification to every saved subscription."""
    settings = request.app.state.settings
    db = request.app.state.db
    return await send_push(
        db, settings,
        {"title": "Hack the Body", "body": "Push is working.", "url": "/"},
    )
