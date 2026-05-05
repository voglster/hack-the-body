"""Garmin-side cleanup of treadmill duplicate uploads.

Companion to cleanup_treadmill_dupes (which scrubs Mongo). The Mongo
cleanup couldn't delete the Garmin activities because we'd stored
uploadId (the upload reference) rather than the real activityId — the
Garmin API 404s on uploadId. So this tool queries Garmin directly,
identifies the dupe cluster from each real session, and deletes by the
authoritative activityId.

Heuristic: group activities by activityType=other (TCX upload type)
into clusters where consecutive items end within END_BUCKET_S of each
other. Within each cluster, keep the one with the largest duration
(most-complete representation of the session) and delete the rest.

Run inside the ingestor container:
  python -m app.cleanup_garmin_dupes [--days N] [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import get_settings
from app.garmin_client import GarminClient

log = logging.getLogger("cleanup-garmin")

# Two activities are considered the same real session if their end
# times fall within this window. The duplicate flood produced
# activities with end times within ~1s of each other; a real second
# workout same-day will be many minutes off.
END_BUCKET_S = 120


def _parse_local(ts: str) -> datetime:
    # Garmin returns "2026-05-04 21:11:35" (no tz). Treat as naive,
    # comparisons stay correct for relative grouping.
    return datetime.fromisoformat(ts.replace(" ", "T"))


def _activity_end(a: dict[str, Any]) -> datetime:
    start = _parse_local(a["startTimeLocal"])
    return start + timedelta(seconds=int(a.get("duration") or 0))


def _is_treadmill_dupe_candidate(a: dict[str, Any]) -> bool:
    # The upload loop pushes TCX with Sport=Other, so only activities
    # of type "other" (and the rare promoted "walking" if set_activity_type
    # ran) are candidates. Skip everything else (cycling, runs, etc.).
    type_key = (a.get("activityType") or {}).get("typeKey") or ""
    return type_key in {"other", "walking", "fitness_equipment"}


def _cluster(activities: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    activities = sorted(activities, key=_activity_end)
    clusters: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    last_end: datetime | None = None
    for a in activities:
        end = _activity_end(a)
        if last_end is None or (end - last_end).total_seconds() <= END_BUCKET_S:
            current.append(a)
        else:
            clusters.append(current)
            current = [a]
        last_end = end
    if current:
        clusters.append(current)
    return clusters


def _pick_canonical(cluster: list[dict[str, Any]]) -> dict[str, Any]:
    return max(cluster, key=lambda a: a.get("duration") or 0)


def _run(*, days: int, dry_run: bool) -> None:
    settings = get_settings()
    client = GarminClient(settings)
    client.login()

    end = datetime.now(UTC).date()
    start = end - timedelta(days=days)
    activities = client.fetch_workouts(start, end)
    log.info("fetched %d activities in %s..%s", len(activities), start, end)

    candidates = [a for a in activities if _is_treadmill_dupe_candidate(a)]
    log.info("treadmill-shaped (other/walking/fitness_equipment): %d", len(candidates))

    clusters = _cluster(candidates)
    log.info("clusters by end-time (within %ds): %d", END_BUCKET_S, len(clusters))

    losers: list[dict[str, Any]] = []
    for cluster in clusters:
        if len(cluster) <= 1:
            continue
        canonical = _pick_canonical(cluster)
        losers.extend(a for a in cluster if a["activityId"] != canonical["activityId"])
        log.info(
            "cluster end~%s: keep %s (dur=%ss) — drop %d siblings",
            _activity_end(canonical).isoformat(timespec="seconds"),
            canonical["activityId"], int(canonical.get("duration") or 0),
            len(cluster) - 1,
        )

    log.info("plan: delete %d Garmin activities", len(losers))
    if dry_run:
        log.info("DRY RUN — no deletes performed")
        return

    deleted = 0
    failed = 0
    for a in losers:
        aid = a["activityId"]
        try:
            client.delete_activity(aid)
            deleted += 1
        except Exception as e:
            log.warning("delete %s failed: %s", aid, e)
            failed += 1
        if deleted and deleted % 50 == 0:
            log.info("progress: %d deleted, %d failed", deleted, failed)
    log.info("done: %d deleted, %d failed", deleted, failed)


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=14,
                   help="lookback window for fetching Garmin activities")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    _run(days=args.days, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
