"""User-set targets: storage, validation, defaults."""
from datetime import UTC, datetime, timedelta

HEADERS = {"X-API-Key": "test-key"}


async def test_get_targets_returns_nulls_when_unset(client):
    """Cold-start: every target is null. The coach treats null as
    'don't judge against this metric'."""
    r = await client.get("/profile/targets", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["daily_calories"] is None
    assert body["daily_protein_g"] is None
    assert body["step_goal_override"] is None


async def test_put_then_get_round_trip(client):
    r = await client.put(
        "/profile/targets", headers=HEADERS,
        json={"daily_calories": 2200, "daily_protein_g": 180,
              "daily_water_oz": 128, "step_goal_override": 12000},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["daily_calories"] == 2200
    assert body["daily_protein_g"] == 180
    assert body["daily_water_oz"] == 128
    assert body["step_goal_override"] == 12000
    assert body["updated_at"] is not None

    # GET sees the same values.
    r = await client.get("/profile/targets", headers=HEADERS)
    assert r.json()["daily_calories"] == 2200
    assert r.json()["daily_water_oz"] == 128


async def test_partial_put_leaves_unset_fields_untouched(client):
    """PUT semantics: only fields explicitly present in the body are
    written. Omitted fields are left untouched. To clear a field, send
    it explicitly as `null`. (FE always sends the full body, but ad-hoc
    curl callers shouldn't accidentally wipe siblings.)"""
    await client.put(
        "/profile/targets", headers=HEADERS,
        json={"daily_calories": 2200, "daily_protein_g": 180},
    )
    # Update only calories — protein_g stays put.
    await client.put(
        "/profile/targets", headers=HEADERS,
        json={"daily_calories": 2300},
    )
    r = await client.get("/profile/targets", headers=HEADERS)
    body = r.json()
    assert body["daily_calories"] == 2300
    assert body["daily_protein_g"] == 180

    # Explicit null clears.
    await client.put(
        "/profile/targets", headers=HEADERS,
        json={"daily_protein_g": None},
    )
    r = await client.get("/profile/targets", headers=HEADERS)
    body = r.json()
    assert body["daily_calories"] == 2300
    assert body["daily_protein_g"] is None


async def test_put_rejects_out_of_range(client):
    r = await client.put(
        "/profile/targets", headers=HEADERS,
        json={"daily_calories": 99999},  # > 10000 max
    )
    assert r.status_code == 422


async def test_targets_require_auth(client):
    r = await client.get("/profile/targets")
    assert r.status_code == 401
    r = await client.put("/profile/targets", json={"daily_calories": 2200})
    assert r.status_code == 401


# ---------- day note ----------

async def test_day_note_unset_returns_empty(client):
    r = await client.get("/profile/day-note", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == ""
    assert body["is_today"] is False


async def test_day_note_round_trip(client):
    r = await client.put(
        "/profile/day-note", headers=HEADERS,
        json={"text": "dinner out at friend's tonight, eating late"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "friend" in body["text"]
    assert body["is_today"] is True
    assert body["local_date"] is not None

    # GET sees the same.
    r = await client.get("/profile/day-note", headers=HEADERS)
    assert r.json()["text"].startswith("dinner out")


async def test_day_note_empty_body_clears(client):
    await client.put(
        "/profile/day-note", headers=HEADERS, json={"text": "earlier note"},
    )
    r = await client.put("/profile/day-note", headers=HEADERS, json={"text": ""})
    assert r.json()["text"] == ""
    r = await client.get("/profile/day-note", headers=HEADERS)
    assert r.json()["text"] == ""


async def test_day_note_delete(client):
    await client.put(
        "/profile/day-note", headers=HEADERS, json={"text": "to be deleted"},
    )
    r = await client.delete("/profile/day-note", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["text"] == ""


async def test_day_note_stale_date_returns_empty(client, mock_db):
    """A note whose `local_date` is yesterday must not leak into today's
    response — coach prompts would carry stale context across midnight."""
    yesterday = (datetime.now(UTC) - timedelta(days=1)).date().isoformat()
    await mock_db["user_profile"].update_one(
        {"_id": "day_note"},
        {"$set": {"text": "yesterday's note", "local_date": yesterday,
                  "set_at": datetime.now(UTC) - timedelta(days=1)}},
        upsert=True,
    )
    r = await client.get("/profile/day-note", headers=HEADERS)
    body = r.json()
    assert body["text"] == ""
    assert body["is_today"] is False


async def test_day_note_require_auth(client):
    r = await client.get("/profile/day-note")
    assert r.status_code == 401
    r = await client.put("/profile/day-note", json={"text": "x"})
    assert r.status_code == 401


# ---------- coach note ----------

async def test_coach_note_unset_returns_empty(client):
    r = await client.get("/profile/coach-note", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == ""
    assert body["updated_at"] is None


async def test_coach_note_round_trip(client):
    r = await client.put(
        "/profile/coach-note", headers=HEADERS,
        json={"text": "Trying to lose weight slowly. Under target is fine."},
    )
    assert r.status_code == 200, r.text
    assert "lose weight" in r.json()["text"]
    assert r.json()["updated_at"] is not None
    r = await client.get("/profile/coach-note", headers=HEADERS)
    assert "lose weight" in r.json()["text"]


async def test_coach_note_require_auth(client):
    r = await client.get("/profile/coach-note")
    assert r.status_code == 401
