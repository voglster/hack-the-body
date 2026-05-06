"""One-off cleanup: drop sub-threshold treadmill workouts from Mongo.

Pre-dates the `_is_real_workout` filter added to the aggregator
(commit b8fb17b). Sessions that don't clear ALL of:
  - duration_s    >= MIN_REAL_DURATION_S
  - active_s      >= MIN_REAL_ACTIVE_S
  - distance_mi   >= MIN_REAL_DISTANCE_MI
are not real workouts (firmware update, accidental power-on, brief
deck test). The aggregator now drops them on finalize, but rows
written before the filter shipped still pollute `workouts`.

Mongo-only by default. Pass --garmin to also delete the matching
Garmin activities for any rows that have a stored garmin_activity_id.

Run inside the ingestor container:
  python -m app.cleanup_treadmill_subthreshold [--dry-run] [--garmin]
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any

from pymongo import AsyncMongoClient

from app.config import get_settings
from app.garmin_client import GarminClient

# Keep these in sync with services/api/app/services/treadmill_aggregator.py
MIN_REAL_DURATION_S = 120
MIN_REAL_ACTIVE_S = 60
MIN_REAL_DISTANCE_MI = 0.05

SOURCE = "precor-csafe"
_PREVIEW_LIMIT = 20

log = logging.getLogger("cleanup-subthreshold")


def _is_subthreshold(row: dict[str, Any]) -> bool:
    duration = row.get("duration_s") or 0
    active = row.get("active_s") or 0
    distance_mi = row.get("distance_mi")
    if distance_mi is None:
        meters = row.get("distance_m") or 0
        distance_mi = meters / 1609.344
    return (
        duration < MIN_REAL_DURATION_S
        or active < MIN_REAL_ACTIVE_S
        or distance_mi < MIN_REAL_DISTANCE_MI
    )


async def _load(db) -> list[dict[str, Any]]:
    cur = db["workouts"].find(
        {"source": SOURCE},
        projection={
            "_id": 1, "source_id": 1, "started_at": 1, "ended_at": 1,
            "duration_s": 1, "active_s": 1,
            "distance_m": 1, "distance_mi": 1,
            "garmin_activity_id": 1,
        },
    )
    return [d async for d in cur]


def _delete_garmin(settings, rows: list[dict]) -> None:
    client = GarminClient(settings)
    client.login()
    deleted = 0
    failed = 0
    for r in rows:
        aid = r.get("garmin_activity_id")
        if not aid:
            continue
        try:
            client.delete_activity(aid)
            deleted += 1
        except Exception as e:
            log.warning("delete failed for %s: %s", aid, e)
            failed += 1
    log.info("garmin done: %d deleted, %d failed", deleted, failed)


async def _run(*, dry_run: bool, do_garmin: bool) -> None:
    settings = get_settings()
    mongo = AsyncMongoClient(settings.mongo_url, tz_aware=True)
    db = mongo[settings.mongo_db]

    rows = await _load(db)
    log.info("loaded %d treadmill workouts", len(rows))

    losers = [r for r in rows if _is_subthreshold(r)]
    log.info(
        "found %d sub-threshold rows (of %d) — %d have garmin_activity_id",
        len(losers), len(rows),
        sum(1 for r in losers if r.get("garmin_activity_id")),
    )

    for r in losers[:_PREVIEW_LIMIT]:
        log.info(
            "  drop: %s  dur=%ss active=%ss dist_mi=%.3f",
            r.get("source_id"),
            r.get("duration_s"),
            r.get("active_s"),
            (r.get("distance_mi")
             if r.get("distance_mi") is not None
             else (r.get("distance_m") or 0) / 1609.344),
        )
    if len(losers) > _PREVIEW_LIMIT:
        log.info("  ... %d more", len(losers) - _PREVIEW_LIMIT)

    if dry_run:
        log.info("DRY RUN — no writes performed")
        return

    if do_garmin:
        _delete_garmin(settings, losers)

    if losers:
        ids = [r["_id"] for r in losers]
        chunk = 1000
        total = 0
        for i in range(0, len(ids), chunk):
            res = await db["workouts"].delete_many({"_id": {"$in": ids[i:i + chunk]}})
            total += res.deleted_count
        log.info("mongo deleted %d", total)
    log.info("cleanup complete")


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="only print the plan; no writes")
    p.add_argument("--garmin", action="store_true",
                   help="also delete corresponding Garmin activities "
                        "(default is Mongo-only since most sub-threshold "
                        "rows never made it to Garmin anyway)")
    args = p.parse_args()
    asyncio.run(_run(dry_run=args.dry_run, do_garmin=args.garmin))


if __name__ == "__main__":
    main()
