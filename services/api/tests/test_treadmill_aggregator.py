"""Tests for the treadmill pull-on-read aggregator."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.treadmill_aggregator import (
    SOURCE,
    _aggregate,
    _split_sessions,
    get_active,
)


def _sample(ts: datetime, *, speed=2.0, grade=1.0, dist=100, hr=120, cal=10):
    return {
        "ts": ts,
        "source": SOURCE,
        "speed_mph": speed,
        "grade_pct": grade,
        "distance_raw": dist,
        "hr_bpm": hr,
        "calories": cal,
        "twork_s": 0,
        "state": 9,
    }


def test_split_sessions_one_continuous():
    base = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    samples = [_sample(base + timedelta(seconds=i)) for i in range(20)]
    sessions = _split_sessions(samples)
    assert len(sessions) == 1
    assert len(sessions[0]) == 20


def test_split_sessions_separated_by_gap():
    base = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    early = [_sample(base + timedelta(seconds=i)) for i in range(10)]
    late = [_sample(base + timedelta(minutes=5, seconds=i)) for i in range(10)]
    sessions = _split_sessions(early + late)
    assert len(sessions) == 2
    assert len(sessions[0]) == 10
    assert len(sessions[1]) == 10


def test_aggregate_distance_uses_calibrated_unit():
    base = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    samples = [
        _sample(base, dist=1000),
        _sample(base + timedelta(seconds=60), dist=1100),
    ]
    summary = _aggregate(samples, status="complete")
    # 100 counts * 0.001 mi/count = 0.1 mi
    assert summary.distance_mi == 0.1


def test_aggregate_hr_zones_distributed():
    base = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    # 10 samples at 1Hz, all hr=140 -> all in z3 (130-150)
    samples = [_sample(base + timedelta(seconds=i), hr=140) for i in range(10)]
    summary = _aggregate(samples, status="complete")
    assert summary.hr_zones_s["z3"] >= 8  # most of the 10 seconds in z3
    assert summary.hr_zones_s["z1"] == 0
    assert summary.hr_zones_s["z5"] == 0


def test_aggregate_zero_speed_not_counted_active():
    base = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    samples = [
        _sample(base + timedelta(seconds=i), speed=0.0)
        for i in range(10)
    ] + [
        _sample(base + timedelta(seconds=10 + i), speed=2.0)
        for i in range(10)
    ]
    summary = _aggregate(samples, status="complete")
    # half the samples were active -> ~half active_s
    assert 8 <= summary.active_s <= 11


def test_aggregate_distance_handles_u16_wrap():
    base = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    # raw counter wrapped from 65500 -> 100. Real delta = 100 + (65536 - 65500) = 136
    samples = [_sample(base, dist=65500), _sample(base + timedelta(seconds=60), dist=100)]
    summary = _aggregate(samples, status="complete")
    assert abs(summary.distance_mi - 0.136) < 1e-6


def test_aggregate_no_hr_when_strap_missing():
    base = datetime(2026, 5, 1, 12, 0, 0, tzinfo=UTC)
    samples = [_sample(base + timedelta(seconds=i), hr=0) for i in range(10)]
    summary = _aggregate(samples, status="complete")
    assert summary.avg_hr is None
    assert summary.max_hr is None


@pytest.mark.asyncio
async def test_get_active_returns_none_for_empty(mock_db):
    summary = await get_active(mock_db)
    assert summary is None


@pytest.mark.asyncio
async def test_get_active_finalizes_completed_session(mock_db, monkeypatch):
    # Old samples — well outside the active window.
    base = datetime.now(UTC) - timedelta(hours=2)
    docs = [_sample(base + timedelta(seconds=i)) for i in range(30)]
    await mock_db["treadmill_samples"].insert_many(docs)

    summary = await get_active(mock_db)
    # Most-recent session ended >30s ago -> finalized + returned (status complete).
    assert summary is not None
    assert summary.status == "complete"
    assert summary.sample_count == 30

    # And the workouts collection got a doc.
    stored = await mock_db["workouts"].find_one({"source": SOURCE})
    assert stored is not None
    assert stored["status"] == "complete"

    # Calling again should not produce a duplicate workout.
    await get_active(mock_db)
    count = await mock_db["workouts"].count_documents({"source": SOURCE})
    assert count == 1


@pytest.mark.asyncio
async def test_get_active_returns_active_when_recent_samples(mock_db):
    now = datetime.now(UTC)
    # 10 samples ending 5s ago - should still be active
    docs = [_sample(now - timedelta(seconds=15 - i)) for i in range(10)]
    await mock_db["treadmill_samples"].insert_many(docs)

    summary = await get_active(mock_db)
    assert summary is not None
    assert summary.status == "active"

    # No persisted doc yet — active sessions don't write to `workouts`.
    count = await mock_db["workouts"].count_documents({"source": SOURCE})
    assert count == 0


@pytest.mark.asyncio
async def test_get_active_finalizes_old_session_and_returns_active_new(mock_db):
    now = datetime.now(UTC)
    # Old session 90 minutes ago
    old_base = now - timedelta(minutes=90)
    old_docs = [_sample(old_base + timedelta(seconds=i)) for i in range(20)]
    # Active session right now
    new_docs = [_sample(now - timedelta(seconds=10 - i)) for i in range(10)]
    await mock_db["treadmill_samples"].insert_many(old_docs + new_docs)

    summary = await get_active(mock_db)
    # Returns the active session
    assert summary is not None
    assert summary.status == "active"
    # But finalized the old one in the background
    count = await mock_db["workouts"].count_documents({"source": SOURCE})
    assert count == 1
