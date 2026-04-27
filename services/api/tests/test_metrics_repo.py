from datetime import UTC, datetime, timedelta

from app.models.metrics import DailySummary, Sleep, Weight
from app.services.metrics_repo import MetricsRepo


async def test_insert_and_latest_weight(mock_db):
    repo = MetricsRepo(mock_db)
    now = datetime.now(UTC)
    await repo.insert_weight(
        Weight(ts=now, kg=108.9, source="garmin", source_id="w1")
    )
    latest = await repo.latest_weight()
    assert latest is not None
    assert latest["kg"] == 108.9


async def test_range_weight_returns_ordered(mock_db):
    repo = MetricsRepo(mock_db)
    base = datetime(2026, 4, 1, 7, 0, tzinfo=UTC)
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
    now = datetime.now(UTC)
    await repo.insert_sleep(
        Sleep(ts=now, duration_s=27000, deep_s=3600, rem_s=5400,
              light_s=16000, awake_s=2000, score=80,
              source="garmin", source_id="s1")
    )
    latest = await repo.latest_sleep()
    assert latest["duration_s"] == 27000


async def test_latest_daily_summary_skips_stub_future_row(mock_db):
    """Regression: a stub `daily_summary` for 'tomorrow UTC' (Mountain
    user past 6 PM) used to win latest-by-ts and hide the real row,
    making the dashboard 'lose' its step goal. Prefer rows with a
    step_goal set."""
    repo = MetricsRepo(mock_db)
    real = datetime(2026, 4, 26, 0, 0, tzinfo=UTC)
    stub = datetime(2026, 4, 27, 0, 0, tzinfo=UTC)
    await repo.insert_daily_summary(
        DailySummary(ts=real, steps=9000, step_goal=12000, total_kcal=2200,
                     active_kcal=400, source="garmin", source_id="ds:real"),
    )
    await repo.insert_daily_summary(
        DailySummary(ts=stub, steps=0, step_goal=None,
                     source="garmin", source_id="ds:stub"),
    )
    latest = await repo.latest_daily_summary()
    assert latest is not None
    assert latest["step_goal"] == 12000
    assert latest["steps"] == 9000


async def test_latest_daily_summary_falls_back_when_no_goal_anywhere(mock_db):
    """If no row has step_goal (cold-start day), still return *something*."""
    repo = MetricsRepo(mock_db)
    await repo.insert_daily_summary(
        DailySummary(ts=datetime(2026, 4, 26, 0, 0, tzinfo=UTC),
                     steps=300, step_goal=None,
                     source="garmin", source_id="ds:nogoal"),
    )
    latest = await repo.latest_daily_summary()
    assert latest is not None
    assert latest["steps"] == 300
