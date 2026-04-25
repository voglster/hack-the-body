from datetime import datetime, timedelta, timezone

from app.models.metrics import Weight, Sleep
from app.services.metrics_repo import MetricsRepo


async def test_insert_and_latest_weight(mock_db):
    repo = MetricsRepo(mock_db)
    now = datetime.now(timezone.utc)
    await repo.insert_weight(
        Weight(ts=now, kg=108.9, source="garmin", source_id="w1")
    )
    latest = await repo.latest_weight()
    assert latest is not None
    assert latest["kg"] == 108.9


async def test_range_weight_returns_ordered(mock_db):
    repo = MetricsRepo(mock_db)
    base = datetime(2026, 4, 1, 7, 0, tzinfo=timezone.utc)
    for i in range(5):
        await repo.insert_weight(
            Weight(ts=base + timedelta(days=i), kg=108 + i * 0.1,
                   source="garmin", source_id=f"w{i}")
        )
    rows = await repo.range_weight(base, base + timedelta(days=10))
    assert len(rows) == 5
    assert rows[0]["ts"] < rows[-1]["ts"]


async def test_insert_sleep_and_latest(mock_db):
    repo = MetricsRepo(mock_db)
    now = datetime.now(timezone.utc)
    await repo.insert_sleep(
        Sleep(ts=now, duration_s=27000, deep_s=3600, rem_s=5400,
              light_s=16000, awake_s=2000, score=80,
              source="garmin", source_id="s1")
    )
    latest = await repo.latest_sleep()
    assert latest["duration_s"] == 27000
