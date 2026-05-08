"""Find finalized treadmill workouts that haven't been pushed to Garmin
yet and upload them as TCX.

Idempotent: each workout has a `garmin_activity_id` (or
`garmin_upload_attempted_at` on duplicates / errors) flag once
processed, so we never re-upload."""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

from app.garmin_client import GarminClient
from app.tcx import build_tcx

log = logging.getLogger(__name__)

SOURCE = "precor-csafe"
# Garmin processes TCX uploads asynchronously — the activityId isn't
# available immediately. Poll a few times before giving up so we don't
# leave the activity classified as "Other".
RESOLVE_ATTEMPTS = 4
RESOLVE_DELAY_S = 2.0


async def _pending(db: AsyncDatabase) -> list[dict[str, Any]]:
    cur = db["workouts"].find({
        "source": SOURCE,
        "status": "complete",
        "garmin_activity_id": {"$exists": False},
        "garmin_upload_skipped": {"$exists": False},
    }).sort("started_at", 1)
    return [w async for w in cur]


async def _stranded(db: AsyncDatabase) -> list[dict[str, Any]]:
    """Workouts that uploaded but never got reclassified to walking — pre-fix
    rows, transient set_activity_type failures, or uploads stored under their
    uploadId because activity-id resolution timed out. Garmin shows them as
    'Other'; we keep retrying until the type sticks."""
    cur = db["workouts"].find({
        "source": SOURCE,
        "garmin_activity_id": {"$exists": True},
        "garmin_type_corrected": {"$ne": True},
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
    """Upload every pending treadmill workout, then retry reclassify on any
    previously-uploaded rows still stranded as 'Other'. Returns counts dict."""
    counts = {"uploaded": 0, "duplicate": 0, "failed": 0, "retyped": 0, "retype_failed": 0}
    pending = await _pending(db)
    stranded = await _stranded(db)
    if not pending and not stranded:
        return counts

    client.login()
    for workout in pending:
        wid = workout["source_id"]
        try:
            samples = await _samples_for(db, workout)
            tcx = build_tcx(workout, samples)
            name_hint = workout["started_at"].strftime("treadmill-%Y%m%dT%H%M%S")
            result = client.upload_tcx(tcx, name_hint=name_hint)
            upload_ref = _extract_activity_id(result)
            if upload_ref:
                real_id = upload_ref if _is_real_activity_id(result) else None
                if real_id is None:
                    real_id = await _resolve_real_activity_id(
                        client, workout["started_at"],
                    )
                type_corrected = False
                final_id: int | str = real_id if real_id is not None else upload_ref
                if real_id is not None:
                    try:
                        client.set_activity_type_walking(real_id)
                        type_corrected = True
                    except Exception:
                        log.exception(
                            "failed to set walking type for activity %s",
                            real_id,
                        )
                await db["workouts"].update_one(
                    {"_id": workout["_id"]},
                    {"$set": {
                        "garmin_activity_id": final_id,
                        "garmin_uploaded_at": datetime.now(UTC),
                        "garmin_type_corrected": type_corrected,
                    }},
                )
                counts["uploaded"] += 1
                log.info("uploaded treadmill workout %s -> garmin %s (walking=%s)",
                         wid, final_id, type_corrected)
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

    for workout in stranded:
        wid = workout["source_id"]
        try:
            stored_id = workout["garmin_activity_id"]
            # Stored id may be a Garmin uploadId (no activity yet) instead of
            # a real activityId. Resolve from start time to get the real one.
            real_id = await _resolve_real_activity_id(client, workout["started_at"])
            target_id = real_id if real_id is not None else stored_id
            client.set_activity_type_walking(target_id)
            await db["workouts"].update_one(
                {"_id": workout["_id"]},
                {"$set": {
                    "garmin_activity_id": target_id,
                    "garmin_type_corrected": True,
                    "garmin_type_corrected_at": datetime.now(UTC),
                }},
            )
            counts["retyped"] += 1
            log.info("retyped stranded workout %s -> walking on %s", wid, target_id)
        except Exception:
            counts["retype_failed"] += 1
            log.exception("retype failed for stranded workout %s", wid)
    return counts


async def _resolve_real_activity_id(
    client: GarminClient, started_at: datetime,
) -> int | None:
    """Poll Garmin a few times for the activity that just landed.

    TCX uploads come back with only an uploadId; the real activityId
    appears on Garmin's side a beat later as the upload is processed.
    Try a handful of times with a small delay; return None if the
    activity never shows up (caller leaves it as Other and we can fix
    it by hand)."""
    for attempt in range(RESOLVE_ATTEMPTS):
        try:
            aid = client.find_activity_by_start_time(started_at)
        except Exception:
            log.exception("activity lookup failed (attempt %d)", attempt + 1)
            aid = None
        if aid is not None:
            return aid
        if attempt < RESOLVE_ATTEMPTS - 1:
            await asyncio.sleep(RESOLVE_DELAY_S)
    return None


def _is_real_activity_id(result: Any) -> bool:
    """True only when the upload response gave us a real activityId (i.e. a
    successes[0].internalId). The fallback uploadId/uploadUuid path is for
    duplicates or async-pending uploads where the activity doesn't exist yet
    and set_activity_type would 404."""
    if not isinstance(result, dict):
        return False
    detail = result.get("detailedImportResult") or {}
    successes = detail.get("successes") or []
    if not successes:
        return False
    first = successes[0] or {}
    return bool(first.get("internalId") or first.get("id"))


def _extract_activity_id(result: Any) -> int | str | None:
    """Garmin's upload response shape varies. Sometimes it's
    {detailedImportResult: {successes: [{internalId}]}}; in practice for
    our TCX uploads it returns {detailedImportResult: {uploadId, ...,
    successes: []}} where uploadId is the unique reference. Fall back
    through known keys."""
    if not isinstance(result, dict):
        return None
    detail = result.get("detailedImportResult") or {}
    successes = detail.get("successes") or []
    if successes:
        first = successes[0] or {}
        if first.get("internalId") or first.get("id"):
            return first.get("internalId") or first.get("id")
    # Fallback: top-level uploadId / uploadUuid. Garmin processes the
    # file async into an activity; uploadId is our handle to it.
    if detail.get("uploadId"):
        return detail["uploadId"]
    uuid = (detail.get("uploadUuid") or {}).get("uuid")
    if uuid:
        return uuid
    return None
