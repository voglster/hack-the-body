"""Water tracking tests."""

HEADERS = {"X-API-Key": "test-key"}


async def test_log_water_creates_entry_and_food(client, mock_db):
    r = await client.post("/water/log", headers=HEADERS, json={"oz": 8})
    assert r.status_code == 201, r.text

    foods = await mock_db["foods"].count_documents({"name": "Water"})
    assert foods == 1
    entries = await mock_db["meal_entries"].count_documents({"food_name": "Water"})
    assert entries == 1


async def test_water_today_total(client):
    await client.post("/water/log", headers=HEADERS, json={"oz": 8})
    await client.post("/water/log", headers=HEADERS, json={"oz": 16})
    await client.post("/water/log", headers=HEADERS, json={"oz": 12.5})

    r = await client.get("/water/today", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["entries"] == 3
    assert body["oz"] == 36.5


async def test_log_water_validation(client):
    r = await client.post("/water/log", headers=HEADERS, json={"oz": 0})
    assert r.status_code == 422
    r = await client.post("/water/log", headers=HEADERS, json={"oz": -5})
    assert r.status_code == 422
    r = await client.post("/water/log", headers=HEADERS, json={"oz": 9999})
    assert r.status_code == 422


async def test_water_requires_auth(client):
    r = await client.post("/water/log", json={"oz": 8})
    assert r.status_code == 401
    r = await client.get("/water/today")
    assert r.status_code == 401
