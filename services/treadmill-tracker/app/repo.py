"""Mongo writer for treadmill_samples time-series collection."""
from __future__ import annotations

from datetime import UTC, datetime

from pymongo.asynchronous.database import AsyncDatabase

from app.poller import Sample


async def ensure_collection(db: AsyncDatabase) -> None:
    """Create treadmill_samples as a time-series collection with TTL."""
    existing = await db.list_collection_names()
    if "treadmill_samples" in existing:
        return
    await db.create_collection(
        "treadmill_samples",
        timeseries={
            "timeField": "ts",
            "metaField": "source",
            "granularity": "seconds",
        },
        # 90 day TTL — workouts are aggregated lazily on read; raw
        # samples beyond ~3 months are not useful.
        expireAfterSeconds=90 * 24 * 3600,
    )


async def write_sample(db: AsyncDatabase, sample: Sample) -> None:
    doc = {
        "ts": sample.ts,
        "source": "precor-csafe",
        "state": sample.state,
        "speed_mph": sample.speed_mph,
        "grade_pct": sample.grade_pct,
        "distance_raw": sample.distance_raw,
        "calories": sample.calories,
        "twork_s": sample.twork_s,
        "hr_bpm": sample.hr_bpm,
    }
    await db["treadmill_samples"].insert_one(doc)


async def write_log(
    db: AsyncDatabase, *, status: str, started_at: datetime, error: str | None = None,
) -> None:
    await db["ingestion_log"].insert_one({
        "source": "treadmill",
        "status": status,
        "kind": "tracker",
        "started_at": started_at,
        "finished_at": datetime.now(UTC),
        "error": error,
    })
