"""Find finalized treadmill workouts that haven't been pushed to Garmin
yet and upload them as TCX.

Idempotent: each workout has a `garmin_activity_id` (or
`garmin_upload_attempted_at` on duplicates / errors) flag once
processed, so we never re-upload."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from app.garmin_client import GarminClient
from app.tcx import build_tcx

log = logging.getLogger(__name__)

SOURCE = "precor-csafe"


async def _pending(db: AsyncDatabase) -> list[dict[str, Any]]:
    cur = db["workouts"].find({
        "source": SOURCE,
        "status": "complete",
        "garmin_activity_id": {"$exists": False},
        "garmin_upload_skipped": {"$exists": False},
    }).sort("started_at", 1)
    return [w async for w in cur]


async def _samples_for(db: AsyncDatabase, workout: dict[str, Any]) -> list[dict[str, Any]]:
    started = workout["started_at"]
    ended = workout["ended_at"]
    cur = db["treadmill_samples"].find(
        {"source": SOURCE, "ts": {"$gte": started, "$lte": ended}},
        sort=[("ts", 1)],
    )
    return [d async for d in cur]


async def upload_pending(db: AsyncDatabase, client: GarminClient) -> dict[str, int]:
    """Upload every pending treadmill workout. Returns counts dict."""
    counts = {"uploaded": 0, "duplicate": 0, "failed": 0}
    pending = await _pending(db)
    if not pending:
        return counts

    client.login()
    for workout in pending:
        wid = workout["source_id"]
        try:
            samples = await _samples_for(db, workout)
            tcx = build_tcx(workout, samples)
            name_hint = workout["started_at"].strftime("treadmill-%Y%m%dT%H%M%S")
            result = client.upload_tcx(tcx, name_hint=name_hint)
            activity_id = _extract_activity_id(result)
            if activity_id:
                await db["workouts"].update_one(
                    {"_id": workout["_id"]},
                    {"$set": {
                        "garmin_activity_id": activity_id,
                        "garmin_uploaded_at": datetime.now(UTC),
                    }},
                )
                counts["uploaded"] += 1
                log.info("uploaded treadmill workout %s -> garmin %s",
                         wid, activity_id)
            else:
                # 409 duplicate or unrecognized response — still mark so we
                # don't keep retrying forever.
                await db["workouts"].update_one(
                    {"_id": workout["_id"]},
                    {"$set": {
                        "garmin_upload_skipped": "duplicate-or-unknown",
                        "garmin_upload_response": str(result)[:500],
                        "garmin_uploaded_at": datetime.now(UTC),
                    }},
                )
                counts["duplicate"] += 1
                log.info("treadmill workout %s upload returned no id (likely duplicate)", wid)
        except Exception as e:
            counts["failed"] += 1
            log.exception("upload failed for treadmill workout %s", wid)
            await db["workouts"].update_one(
                {"_id": workout["_id"]},
                {"$set": {
                    "garmin_last_error": str(e)[:500],
                    "garmin_last_error_at": datetime.now(UTC),
                }},
            )
    return counts


def _extract_activity_id(result: Any) -> int | str | None:
    """Garmin returns either {detailedImportResult: {successes: [{internalId}]}}
    or a flat status dict. Find the new activity id, or None if absent."""
    if not isinstance(result, dict):
        return None
    detail = result.get("detailedImportResult") or {}
    successes = detail.get("successes") or []
    if successes:
        first = successes[0] or {}
        return first.get("internalId") or first.get("id")
    return None
