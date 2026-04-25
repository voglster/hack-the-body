"""Web Push (VAPID) helpers.

VAPID keys come from settings; if they're empty we auto-generate a P-256
ECDSA keypair on startup and persist it in user_profile so the same keys
are reused across restarts. Subscriptions are stored in push_subscriptions
keyed by endpoint.
"""
from __future__ import annotations

import base64
import json
import logging
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pymongo.asynchronous.database import AsyncDatabase
from pywebpush import WebPushException, webpush

from app.config import Settings

logger = logging.getLogger(__name__)

USER_PROFILE_KEY = "vapid"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _generate_keypair() -> tuple[str, str]:
    """Return (private_key_pem_str, public_key_b64url_uncompressed_point)."""
    priv = ec.generate_private_key(ec.SECP256R1())
    pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    # Public key: uncompressed point (0x04 || X || Y), then base64url.
    pub_bytes = priv.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    return pem, _b64url(pub_bytes)


async def ensure_vapid_keys(settings: Settings, db: AsyncDatabase) -> tuple[str, str]:
    """Return (public_b64url, private_pem) for the running app.

    Order of preference:
    1. Both env vars set: use them.
    2. user_profile has a saved keypair: use it.
    3. Generate, save to user_profile, use it.
    """
    if settings.vapid_public_key and settings.vapid_private_key:
        return settings.vapid_public_key, settings.vapid_private_key

    saved = await db["user_profile"].find_one({"_id": USER_PROFILE_KEY})
    if saved and saved.get("public_key") and saved.get("private_key"):
        return saved["public_key"], saved["private_key"]

    private_pem, public_b64 = _generate_keypair()
    await db["user_profile"].update_one(
        {"_id": USER_PROFILE_KEY},
        {"$set": {
            "public_key": public_b64,
            "private_key": private_pem,
            "generated_at": datetime.now(UTC),
        }},
        upsert=True,
    )
    logger.info("Generated and persisted new VAPID keypair")
    return public_b64, private_pem


# ---------- subscriptions ----------

async def save_subscription(db: AsyncDatabase, sub: dict[str, Any]) -> dict[str, Any]:
    endpoint = sub.get("endpoint")
    if not endpoint:
        raise ValueError("subscription missing endpoint")
    await db["push_subscriptions"].update_one(
        {"endpoint": endpoint},
        {"$set": {"endpoint": endpoint, "keys": sub.get("keys"),
                  "updated_at": datetime.now(UTC)}},
        upsert=True,
    )
    stored = await db["push_subscriptions"].find_one({"endpoint": endpoint})
    return stored or {}


async def list_subscriptions(db: AsyncDatabase) -> list[dict[str, Any]]:
    cur = db["push_subscriptions"].find()
    return [d async for d in cur]


async def delete_subscription_by_endpoint(db: AsyncDatabase, endpoint: str) -> int:
    res = await db["push_subscriptions"].delete_one({"endpoint": endpoint})
    return res.deleted_count


# ---------- send ----------

async def send_push(
    db: AsyncDatabase,
    settings: Settings,
    payload: dict[str, Any],
    *,
    ttl: int = 60 * 60,
) -> dict[str, int]:
    """Best-effort push to every saved subscription.

    Stale (410/404) endpoints are deleted on the way through. Returns counts.
    """
    public_key, private_pem = await ensure_vapid_keys(settings, db)
    _ = public_key  # private only for sending
    subs = await list_subscriptions(db)
    sent = 0
    pruned = 0
    failed = 0
    body = json.dumps(payload, default=str)
    for s in subs:
        sub_info = {"endpoint": s["endpoint"], "keys": s.get("keys")}
        try:
            webpush(
                subscription_info=sub_info,
                data=body,
                vapid_private_key=private_pem,
                vapid_claims={"sub": settings.vapid_subject},
                ttl=ttl,
            )
            sent += 1
        except WebPushException as e:
            status = e.response.status_code if e.response is not None else None
            if status in (404, 410):
                await delete_subscription_by_endpoint(db, s["endpoint"])
                pruned += 1
            else:
                logger.warning("push failed (%s): %s", status, e)
                failed += 1
        except Exception:
            logger.exception("push send error")
            failed += 1
    return {"sent": sent, "pruned": pruned, "failed": failed,
            "subscriptions": len(subs)}
