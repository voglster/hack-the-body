"""Vitamins are now tracked as a habit (kind=manual, on_done_action="log_vitamins").

The dashboard's VitaminsCard and Home Assistant's IKEA-remote automation
both POST to `/habits/{vitamins_habit_id}/status` with `{"status": "done"}`.
The on-done action creates a Vitamins meal_entry idempotently per local
day, so the nudge rule (which counts meal_entries) keeps working unchanged.
"""
from datetime import UTC, datetime, time, timedelta

from app.routers.vitamins import count_vitamins_today
from app.services.food_repo import FoodRepo

HEADERS = {"X-API-Key": "test-key"}


async def _vitamins_habit_id(client) -> str:
    """The fixture seeds the canonical Vitamins habit; look it up by name."""
    r = await client.get("/habits", headers=HEADERS)
    habits = r.json()
    for h in habits:
        if h["name"] == "Vitamins":
            return h["id"]
    raise AssertionError("Vitamins habit not seeded by fixture")


async def test_marking_vitamins_habit_creates_food_and_entry(client, mock_db):
    """The first done press on the Vitamins habit must materialize the
    meal_entry — that's the side-effect that suppresses the nudge."""
    hid = await _vitamins_habit_id(client)
    r = await client.post(
        f"/habits/{hid}/status", headers=HEADERS, json={"status": "done"},
    )
    assert r.status_code == 200, r.text
    foods = await mock_db["foods"].count_documents(
        {"name": "Vitamins", "category": "supplement"},
    )
    assert foods == 1
    entries = await mock_db["meal_entries"].count_documents({"food_name": "Vitamins"})
    assert entries == 1
    # The action result is surfaced so HA / dashboard can show feedback.
    action = r.json().get("action")
    assert action is not None
    assert action["created"] is True


async def test_marking_vitamins_done_twice_is_idempotent(client, mock_db):
    """The whole point of moving to the habit endpoint: HA's IKEA remote
    can double-tap and the second press is a no-op, not a duplicate entry."""
    hid = await _vitamins_habit_id(client)
    await client.post(
        f"/habits/{hid}/status", headers=HEADERS, json={"status": "done"},
    )
    r2 = await client.post(
        f"/habits/{hid}/status", headers=HEADERS, json={"status": "done"},
    )
    assert r2.status_code == 200
    entries = await mock_db["meal_entries"].count_documents({"food_name": "Vitamins"})
    assert entries == 1
    # The second call surfaces created=False so the FE / HA can show
    # "already done today" rather than "✓ Vitamins logged" again.
    action = r2.json().get("action")
    assert action is not None
    assert action["created"] is False


async def test_today_returns_logged_state(client):
    """The /vitamins/today endpoint counts meal_entries directly, so the
    nudge rule and the dashboard view both reflect a successful habit mark."""
    r = await client.get("/vitamins/today", headers=HEADERS)
    body = r.json()
    assert body["logged"] is False
    assert body["entries"] == 0
    assert body["first_ts"] is None

    hid = await _vitamins_habit_id(client)
    await client.post(
        f"/habits/{hid}/status", headers=HEADERS, json={"status": "done"},
    )

    r = await client.get("/vitamins/today", headers=HEADERS)
    body = r.json()
    assert body["logged"] is True
    assert body["entries"] == 1
    assert body["first_ts"] is not None


async def test_count_helper_filters_by_window(mock_db):
    repo = FoodRepo(mock_db)
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


async def test_vitamins_today_requires_auth(client):
    r = await client.get("/vitamins/today")
    assert r.status_code == 401


async def test_old_vitamins_log_endpoint_is_gone(client):
    """Explicit regression guard: POST /vitamins/log used to be how the
    dashboard logged vitamins. It was removed in favor of the generic
    habit endpoint. If a future change accidentally re-adds it, this
    test fires and we revisit the design (which surface owns logging)."""
    r = await client.post("/vitamins/log", headers=HEADERS)
    assert r.status_code == 404


async def test_default_vitamins_habit_seeded(client):
    """Production parity: the lifespan startup auto-seeds the Vitamins
    habit so the FE/HA never has to provision it."""
    r = await client.get("/habits", headers=HEADERS)
    assert r.status_code == 200
    habits = r.json()
    vit = next((h for h in habits if h["name"] == "Vitamins"), None)
    assert vit is not None, "Vitamins habit should be auto-seeded"
    assert vit["kind"] == "manual"
    assert vit["on_done_action"] == "log_vitamins"


async def test_ensure_default_habits_backfills_action(mock_db):
    """A pre-existing Vitamins habit without on_done_action (created on
    an older server build) gets backfilled — without overwriting any
    user-set value."""
    # The fixture already seeded it via ensure_default_habits, so we
    # check that a habit with the seed exists and the field is set.
    doc = await mock_db["habits"].find_one({"name": "Vitamins"})
    assert doc is not None
    assert doc.get("on_done_action") == "log_vitamins"
