from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.services import rhythm

H = {"X-API-Key": "test-key"}
TZ = ZoneInfo("UTC")


@pytest.fixture(autouse=True)
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")


def _local(h, m=0):
    now = datetime.now(TZ)
    return now.replace(hour=h, minute=m, second=0, microsecond=0)


async def _eat(client, at: datetime, calories=300):
    food = (
        await client.post(
            "/foods",
            headers=H,
            json={
                "name": f"Meal {at.isoformat()}",
                "serving_g": 100,
                "per_serving": {"calories": calories},
            },
        )
    ).json()
    await client.post(
        "/meals/entries",
        headers=H,
        json={"food_id": food["id"], "quantity_g": 100, "ts": at.astimezone(UTC).isoformat()},
    )


def test_lapse_is_two_blank_days_plus_today():
    today = date(2026, 9, 28)
    assert rhythm.is_lapsed({date(2026, 9, 25)}, today)
    assert not rhythm.is_lapsed({date(2026, 9, 26)}, today)
    assert not rhythm.is_lapsed({today}, today)


def test_weekly_weight_by_tracking():
    mon = date(2026, 5, 4)
    logged = {mon + timedelta(days=i) for i in range(6)}
    weights = [
        (mon, 113.0),
        (mon + timedelta(days=6), 112.0),
        (mon + timedelta(days=7), 112.0),
        (mon + timedelta(days=13), 112.5),
    ]
    out = rhythm.weekly_weight_by_tracking(logged, weights)
    assert out["tracked_lb_per_week"] == -2.2
    assert out["untracked_lb_per_week"] == 1.1


async def test_mid_window_push_only_when_nothing_logged(mock_db):
    pushes = await rhythm.due_pushes(mock_db, _local(13, 35))
    assert [p["title"] for p in pushes] == ["Log it"]
    assert "Just log one thing" in pushes[0]["body"]  # nothing logged for days = lapsed
    assert await rhythm.due_pushes(mock_db, _local(13, 40)) == []  # once per day


async def test_mid_window_quiet_after_logging(client, mock_db):
    await _eat(client, _local(11, 30))
    await _eat(client, _local(10, 0) - timedelta(days=1))
    assert await rhythm.due_pushes(mock_db, _local(13, 35)) == []


async def test_close_push_asks_for_missed_items(client, mock_db):
    await _eat(client, _local(12, 0))
    pushes = await rhythm.due_pushes(mock_db, _local(19, 10))
    assert [p["body"] for p in pushes] == ["Anything you ate that isn't logged?"]


async def test_status_counts_days_logged(client, mock_db):
    for d in (0, 1, 3):
        await _eat(client, _local(12) - timedelta(days=d))
    s = await rhythm.status(mock_db)
    assert s["days_logged_7d"] == 3
    assert s["logged_today"] is True
    assert s["lapsed"] is False
