"""Push-tick tests for the nudges scheduler."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.services.nudges import nudges_push_tick


@pytest.fixture
def fix_tz(monkeypatch):
    monkeypatch.setenv("TZ", "America/Denver")


@pytest.fixture
def settings():
    return Settings(mongo_url="mongodb://fake", mongo_db="testdb", api_key="test-key")


@pytest.fixture
def mock_send_push(monkeypatch):
    sender = AsyncMock(return_value={"sent": 1, "pruned": 0, "failed": 0, "subscriptions": 1})
    monkeypatch.setattr("app.services.nudges.send_push", sender)
    return sender


class TestPushTick:
    async def test_fires_only_matching_bucket(self, mock_db, settings, fix_tz, mock_send_push):
        # 12:00 MT in UTC is 18:00 UTC (MDT = UTC-6)
        now_utc = datetime(2026, 4, 27, 18, 0, tzinfo=UTC)
        # Nothing seeded → vitamins_missing fires (push_at = 12:00).
        await nudges_push_tick(now_utc, settings, mock_db)
        assert mock_send_push.await_count == 1
        # Title should match the vitamins nudge title.
        payload = mock_send_push.await_args.args[2]
        assert payload["title"] == "Vitamins not taken yet"

    async def test_dismissed_does_not_push(self, mock_db, settings, fix_tz, mock_send_push):
        from app.services.nudge_dismissals import record_dismissal
        now_utc = datetime(2026, 4, 27, 18, 0, tzinfo=UTC)  # 12pm MT
        await record_dismissal(
            mock_db, nudge_id="vitamins_missing", until="end_of_day", now_utc=now_utc,
        )
        await nudges_push_tick(now_utc, settings, mock_db)
        assert mock_send_push.await_count == 0

    async def test_off_bucket_no_push(self, mock_db, settings, fix_tz, mock_send_push):
        # 11:00 MT → no bucket matches.
        now_utc = datetime(2026, 4, 27, 17, 0, tzinfo=UTC)
        await nudges_push_tick(now_utc, settings, mock_db)
        assert mock_send_push.await_count == 0

    async def test_grace_window_5_min(self, mock_db, settings, fix_tz, mock_send_push):
        # 12:04 MT — within ±5 min grace of 12:00 bucket.
        now_utc = datetime(2026, 4, 27, 18, 4, tzinfo=UTC)
        await nudges_push_tick(now_utc, settings, mock_db)
        assert mock_send_push.await_count == 1

    async def test_outside_grace_window(self, mock_db, settings, fix_tz, mock_send_push):
        # 12:06 MT — outside ±5 min grace.
        now_utc = datetime(2026, 4, 27, 18, 6, tzinfo=UTC)
        await nudges_push_tick(now_utc, settings, mock_db)
        assert mock_send_push.await_count == 0
