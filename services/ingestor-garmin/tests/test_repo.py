from datetime import UTC, datetime, timedelta

from app.models import Weight, Workout
from app.repo import GarminRepo


async def test_upsert_weight_idempotent(mock_db):
    repo = GarminRepo(mock_db)
    w = Weight(ts=datetime.now(UTC), kg=108.9, source="garmin", source_id="garmin:weight:1")
    await repo.upsert_weight(w)
    await repo.upsert_weight(w)
    count = await mock_db["metrics_weight"].count_documents({})
    assert count == 1


async def test_upsert_workout_idempotent(mock_db):
    repo = GarminRepo(mock_db)
    w = Workout(
        ts=datetime.now(UTC),
        activity_type="walking",
        duration_s=1800,
        distance_m=2500.0,
        source="garmin",
        source_id="garmin:activity:1",
    )
    await repo.upsert_workout(w)
    await repo.upsert_workout(w)
    count = await mock_db["workouts"].count_documents({})
    assert count == 1


async def test_write_ingest_log(mock_db):
    repo = GarminRepo(mock_db)
    await repo.write_log(
        source="garmin",
        status="ok",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        counts={"weight": 3, "sleep": 1},
    )
    doc = await mock_db["ingestion_log"].find_one({"status": "ok"})
    assert doc["counts"]["weight"] == 3


async def test_consume_requests(mock_db):
    repo = GarminRepo(mock_db)
    await mock_db["ingestion_log"].insert_one({
        "source": "garmin",
        "status": "requested",
        "started_at": datetime.now(UTC),
    })
    pending = await repo.consume_requests("garmin")
    assert pending == ["full"]  # legacy row without `kind` defaults to full
    still = await mock_db["ingestion_log"].count_documents(
        {"source": "garmin", "status": "requested"},
    )
    assert still == 0


async def test_consume_requests_returns_kinds_in_order(mock_db):
    repo = GarminRepo(mock_db)
    now = datetime.now(UTC)
    await mock_db["ingestion_log"].insert_many([
        {"source": "garmin", "status": "requested", "kind": "steps", "started_at": now},
        {"source": "garmin", "status": "requested", "kind": "full",
         "started_at": now + timedelta(seconds=1)},
    ])
    pending = await repo.consume_requests("garmin")
    assert pending == ["steps", "full"]
