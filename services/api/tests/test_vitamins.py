"""Vitamin tracking + reminder cron."""
from datetime import UTC, datetime, time, timedelta

from app.routers.vitamins import count_vitamins_today
from app.services.food_repo import FoodRepo

HEADERS = {"X-API-Key": "test-key"}


async def test_log_vitamins_creates_food_and_entry(client, mock_db):
    r = await client.post("/vitamins/log", headers=HEADERS)
    assert r.status_code == 201, r.text
    foods = await mock_db["foods"].count_documents(
        {"name": "Vitamins", "category": "supplement"},
    )
    assert foods == 1
    entries = await mock_db["meal_entries"].count_documents({"food_name": "Vitamins"})
    assert entries == 1


async def test_today_returns_logged_state(client):
    r = await client.get("/vitamins/today", headers=HEADERS)
    body = r.json()
    assert body["logged"] is False
    assert body["entries"] == 0
    assert body["first_ts"] is None

    await client.post("/vitamins/log", headers=HEADERS)

    r = await client.get("/vitamins/today", headers=HEADERS)
    body = r.json()
    assert body["logged"] is True
    assert body["entries"] == 1
    assert body["first_ts"] is not None


async def test_count_helper_filters_by_window(mock_db):
    # Yesterday's vitamin should not count toward today.
    repo = FoodRepo(mock_db)
    food = await repo.upsert_food_dict(
        {"name": "Vitamins", "category": "supplement", "serving_g": 1.0,
         "per_serving": {}, "source": "builtin"},
    ) if hasattr(repo, "upsert_food_dict") else None
    del food  # not used; we insert raw to control ts
    yesterday = datetime.now(UTC) - timedelta(days=1)
    await mock_db["meal_entries"].insert_one({
        "ts": yesterday, "food_name": "Vitamins", "food_category": "supplement",
        "quantity_g": 1.0, "slot": "supplement", "macros": {}, "meta": {},
    })

    today_start = datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)
    today_end = today_start + timedelta(days=1)
    count, first = await count_vitamins_today(repo, today_start, today_end)
    assert count == 0
    assert first is None


async def test_vitamins_requires_auth(client):
    r = await client.post("/vitamins/log")
    assert r.status_code == 401
    r = await client.get("/vitamins/today")
    assert r.status_code == 401
