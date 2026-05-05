"""One-off cleanup for the treadmill duplicate-workout flood.

Caused by a sliding 6h lookback window in the API aggregator that minted
a fresh source_id every poll, producing hundreds of workout docs per
real session — each separately uploaded to Garmin.

Strategy: group `workouts` rows by (source=precor-csafe, ended_at
truncated to second). In each group, keep the row with the largest
duration_s (the one that captured the full session). Delete the rest
from Mongo, and delete their corresponding activities from Garmin.

Run inside the ingestor container:
  python -m app.cleanup_treadmill_dupes [--dry-run] [--no-garmin]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from collections import defaultdict
from datetime import datetime
from typing import Any

from pymongo import AsyncMongoClient

from app.config import get_settings
from app.garmin_client import GarminClient

log = logging.getLogger("cleanup-dupes")

SOURCE = "precor-csafe"


def _bucket_key(ended_at: datetime) -> str:
    return ended_at.replace(microsecond=0).isoformat()


async def _load_workouts(db) -> list[dict[str, Any]]:
    cur = db["workouts"].find(
        {"source": SOURCE},
        projection={
            "_id": 1, "source_id": 1, "started_at": 1, "ended_at": 1,
            "duration_s": 1, "garmin_activity_id": 1,
            "garmin_upload_skipped": 1,
        },
    )
    return [d async for d in cur]


def _group(rows: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        end = r.get("ended_at")
        if end is None:
            continue
        groups[_bucket_key(end)].append(r)
    return groups


def _pick_canonical(group: list[dict]) -> dict:
    return max(group, key=lambda r: r.get("duration_s") or 0)


def _delete_garmin_activities(settings, losers: list[dict]) -> None:
    client = GarminClient(settings)
    client.login()
    deleted = 0
    failed = 0
    for r in losers:
        aid = r.get("garmin_activity_id")
        if not aid:
            continue
        try:
            client.delete_activity(aid)
            deleted += 1
        except Exception as e:
            # Often 404 if the activity was the uploadId fallback that
            # never promoted. Log and move on.
            log.warning("delete failed for %s: %s", aid, e)
            failed += 1
        if deleted % 50 == 0 and deleted:
            log.info("garmin progress: %d deleted, %d failed", deleted, failed)
    log.info("garmin done: %d deleted, %d failed", deleted, failed)


async def _rewrite_canonicals(db, keepers: list[dict]) -> None:
    for k in keepers:
        new_sid = f"treadmill:end:{_bucket_key(k['ended_at'])}"
        if k.get("source_id") != new_sid:
            await db["workouts"].update_one(
                {"_id": k["_id"]},
                {"$set": {"source_id": new_sid}},
            )


async def _delete_losers(db, losers: list[dict]) -> None:
    if not losers:
        return
    ids = [r["_id"] for r in losers]
    chunk = 1000
    for i in range(0, len(ids), chunk):
        res = await db["workouts"].delete_many({"_id": {"$in": ids[i:i + chunk]}})
        log.info("mongo deleted %d (chunk %d)", res.deleted_count, i // chunk)


async def _run(*, dry_run: bool, do_garmin: bool) -> None:
    settings = get_settings()
    mongo = AsyncMongoClient(settings.mongo_url, tz_aware=True)
    db = mongo[settings.mongo_db]

    rows = await _load_workouts(db)
    log.info("loaded %d treadmill workouts", len(rows))
    groups = _group(rows)
    log.info("collapsed into %d distinct sessions (by ended_at second)", len(groups))

    keepers: list[dict] = []
    losers: list[dict] = []
    for group in groups.values():
        canonical = _pick_canonical(group)
        keepers.append(canonical)
        losers.extend(r for r in group if r["_id"] != canonical["_id"])

    log.info(
        "plan: keep %d, delete %d (Mongo) + delete %d Garmin activities",
        len(keepers), len(losers),
        sum(1 for r in losers if r.get("garmin_activity_id")),
    )

    if dry_run:
        log.info("DRY RUN — no writes performed")
        return

    # Garmin deletes first so a partial run doesn't leave Mongo pointing
    # at activities that still exist.
    if do_garmin:
        _delete_garmin_activities(settings, losers)
    await _rewrite_canonicals(db, keepers)
    await _delete_losers(db, losers)
    log.info("cleanup complete")


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="only print the plan; no writes")
    p.add_argument("--no-garmin", action="store_true",
                   help="skip Garmin activity deletion (Mongo-only cleanup)")
    args = p.parse_args()
    asyncio.run(_run(dry_run=args.dry_run, do_garmin=not args.no_garmin))


if __name__ == "__main__":
    main()
