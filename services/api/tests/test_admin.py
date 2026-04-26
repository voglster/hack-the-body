

async def test_admin_trigger_requires_auth(client):
    r = await client.post("/admin/ingest/garmin")
    assert r.status_code == 401


async def test_admin_trigger_writes_log(client, mock_db):
    r = await client.post("/admin/ingest/garmin", headers={"X-API-Key": "test-key"})
    assert r.status_code == 202
    doc = await mock_db["ingestion_log"].find_one({"source": "garmin", "status": "requested"})
    assert doc is not None


async def test_admin_trigger_unknown_source(client):
    r = await client.post("/admin/ingest/unknown", headers={"X-API-Key": "test-key"})
    assert r.status_code == 404


async def test_clear_food_cache_drops_external_only(client, mock_db):
    h = {"X-API-Key": "test-key"}
    # Seed: an OFF-cached food, a manual food, and a builtin (Water).
    await client.post("/foods", headers=h, json={
        "name": "Cached Bar", "barcode": "111", "category": "food",
        "serving_g": 50, "per_serving": {}, "source": "off",
    })
    await client.post("/foods", headers=h, json={
        "name": "Manual Apple", "category": "food",
        "serving_g": 150, "per_serving": {}, "source": "manual",
    })
    await client.post("/foods", headers=h, json={
        "name": "Water", "category": "drink",
        "serving_g": 240, "per_serving": {}, "source": "builtin",
    })

    r = await client.delete("/admin/foods/cache", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] == 1

    remaining = [d["name"] async for d in mock_db["foods"].find()]
    assert "Manual Apple" in remaining
    assert "Water" in remaining
    assert "Cached Bar" not in remaining


async def test_clear_food_cache_preserves_template_refs(client, mock_db):
    h = {"X-API-Key": "test-key"}
    food = await (await client.post("/foods", headers=h, json={
        "name": "Cached Yogurt", "barcode": "222", "category": "food",
        "serving_g": 170, "per_serving": {}, "source": "off",
    })).aread()
    food_id = (await mock_db["foods"].find_one({"name": "Cached Yogurt"}))["_id"]
    await client.post("/meals/templates", headers=h, json={
        "name": "Stack", "items": [{"food_id": str(food_id), "quantity_g": 170}],
    })

    r = await client.delete("/admin/foods/cache", headers=h)
    assert r.status_code == 200
    assert r.json()["deleted"] == 0
    assert await mock_db["foods"].count_documents({"name": "Cached Yogurt"}) == 1
    del food
