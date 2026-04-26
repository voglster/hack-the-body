"""Foods + meal entries + templates."""


HEADERS = {"X-API-Key": "test-key"}


async def _create_food(client, name="Eggs", per_serving=None, **extra):
    body = {
        "name": name,
        "category": "food",
        "serving_g": 100.0,
        "per_serving": per_serving
            or {"calories": 155, "protein_g": 13, "carbs_g": 1.1, "fat_g": 11},
        **extra,
    }
    r = await client.post("/foods", headers=HEADERS, json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_two_foods_without_barcodes_can_coexist(client):
    # Regression: previously model_dump emitted barcode=null which collided
    # with the sparse unique index once a second no-barcode food existed
    # (E11000 dup key barcode_1: null).
    a = await _create_food(client, name="Water-ish")
    b = await _create_food(client, name="Vitamins-ish")
    assert a["id"] != b["id"]


async def test_create_food_with_barcode_does_not_path_conflict(client):
    # Regression: previously $set+$setOnInsert both wrote `created_at`,
    # which mongo rejected with "Updating the path 'created_at' would
    # create a conflict at 'created_at'".
    body = {
        "name": "Manual Bar", "barcode": "9999999999", "category": "food",
        "serving_g": 50.0, "per_serving": {"calories": 200, "protein_g": 20},
    }
    r = await client.post("/foods", headers=HEADERS, json=body)
    assert r.status_code == 201, r.text


async def test_create_and_search_food(client):
    food = await _create_food(client, name="Whole Eggs", brand="Vital Farms")
    assert food["id"]
    r = await client.get("/foods/search?q=eggs", headers=HEADERS)
    assert r.status_code == 200
    rows = r.json()
    assert any(x["name"] == "Whole Eggs" for x in rows)


async def test_log_entry_scales_macros(client):
    food = await _create_food(
        client,
        name="Greek Yogurt",
        per_serving={"calories": 100, "protein_g": 18, "carbs_g": 6, "fat_g": 0},
    )
    r = await client.post(
        "/meals/entries",
        headers=HEADERS,
        json={"food_id": food["id"], "quantity_g": 200, "slot": "breakfast"},
    )
    assert r.status_code == 201, r.text
    entry = r.json()
    # Doubled (200g vs 100g serving)
    assert entry["macros"]["calories"] == 200
    assert entry["macros"]["protein_g"] == 36


async def test_today_totals_aggregates(client):
    yogurt = await _create_food(
        client, name="Yogurt",
        per_serving={"calories": 100, "protein_g": 10, "carbs_g": 8, "fat_g": 0},
    )
    granola = await _create_food(
        client, name="Granola",
        per_serving={"calories": 450, "protein_g": 10, "carbs_g": 70, "fat_g": 14},
    )
    await client.post(
        "/meals/entries", headers=HEADERS,
        json={"food_id": yogurt["id"], "quantity_g": 200, "slot": "breakfast"})
    await client.post(
        "/meals/entries", headers=HEADERS,
        json={"food_id": granola["id"], "quantity_g": 50, "slot": "breakfast"})

    r = await client.get("/meals/today/totals", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    # 200g yogurt = 200 cal, 20p; 50g granola = 225 cal, 5p
    assert body["totals"]["calories"] == 425.0
    assert body["totals"]["protein_g"] == 25.0
    assert body["entry_count"] == 2
    assert body["by_slot"]["breakfast"]["calories"] == 425.0


async def test_template_one_click_log(client):
    yogurt = await _create_food(
        client, name="Yogurt",
        per_serving={"calories": 100, "protein_g": 10, "carbs_g": 8, "fat_g": 0},
    )
    powder = await _create_food(
        client, name="Whey",
        per_serving={"calories": 400, "protein_g": 80, "carbs_g": 5, "fat_g": 5},
    )

    template = {
        "name": "Morning Stack",
        "default_slot": "breakfast",
        "items": [
            {"food_id": yogurt["id"], "quantity_g": 200},
            {"food_id": powder["id"], "quantity_g": 30},
        ],
    }
    r = await client.post("/meals/templates", headers=HEADERS, json=template)
    assert r.status_code == 201, r.text
    saved = r.json()

    r = await client.post(f"/meals/templates/{saved['id']}/log",
                           headers=HEADERS, json={})
    assert r.status_code == 201
    body = r.json()
    assert body["template"] == "Morning Stack"
    assert len(body["entries"]) == 2

    r = await client.get("/meals/today/totals", headers=HEADERS)
    body = r.json()
    # 200g yogurt = 200 cal; 30g whey = 120 cal
    assert body["totals"]["calories"] == 320.0
    # Total protein: 20 + 24 = 44
    assert body["totals"]["protein_g"] == 44.0


async def test_supplement_logging(client):
    multi = await _create_food(
        client,
        name="Centrum Multi",
        category="supplement",
        serving_g=1.0,
        serving_label="1 tablet",
        per_serving={"calories": 0, "protein_g": 0, "carbs_g": 0, "fat_g": 0},
    )
    r = await client.post(
        "/meals/entries", headers=HEADERS,
        json={"food_id": multi["id"], "quantity_g": 1, "slot": "supplement"},
    )
    assert r.status_code == 201

    r = await client.get("/meals/today/totals", headers=HEADERS)
    body = r.json()
    assert len(body["supplements"]) == 1
    assert body["supplements"][0]["name"] == "Centrum Multi"


async def test_edit_entry_time_and_slot(client):
    food = await _create_food(client)
    r = await client.post(
        "/meals/entries", headers=HEADERS,
        json={"food_id": food["id"], "quantity_g": 100, "slot": "snack"},
    )
    entry_id = r.json()["id"]

    new_ts = "2026-04-25T13:30:00+00:00"
    r = await client.patch(
        f"/meals/entries/{entry_id}", headers=HEADERS,
        json={"ts": new_ts, "slot": "lunch"},
    )
    assert r.status_code == 200, r.text
    moved = r.json()
    assert moved["slot"] == "lunch"
    assert moved["ts"].startswith("2026-04-25T13:30")
    # New id (delete+reinsert pattern), original gone.
    assert moved["id"] != entry_id


async def test_edit_entry_404(client):
    r = await client.patch(
        "/meals/entries/000000000000000000000000",
        headers=HEADERS, json={"slot": "lunch"},
    )
    assert r.status_code == 404


async def test_edit_entry_requires_field(client):
    food = await _create_food(client)
    r = await client.post(
        "/meals/entries", headers=HEADERS,
        json={"food_id": food["id"], "quantity_g": 100, "slot": "snack"},
    )
    entry_id = r.json()["id"]
    r = await client.patch(f"/meals/entries/{entry_id}", headers=HEADERS, json={})
    assert r.status_code == 400


async def test_edit_entry_quantity_recomputes_macros(client):
    food = await _create_food(
        client, name="Vanilla Shake", serving_g=325.0,
        per_serving={"calories": 150, "protein_g": 30, "carbs_g": 2, "fat_g": 2.5},
    )
    r = await client.post(
        "/meals/entries", headers=HEADERS,
        # Simulates the "325 servings" bug: 105625 g logged for one shake.
        json={"food_id": food["id"], "quantity_g": 105625, "slot": "lunch"},
    )
    entry_id = r.json()["id"]
    assert r.json()["macros"]["protein_g"] > 9000  # the broken state

    # Correct it: 1 shake = 325 g.
    r = await client.patch(
        f"/meals/entries/{entry_id}", headers=HEADERS, json={"quantity_g": 325},
    )
    assert r.status_code == 200, r.text
    fixed = r.json()
    assert fixed["quantity_g"] == 325
    assert fixed["servings"] == 1.0
    assert fixed["macros"]["calories"] == 150
    assert fixed["macros"]["protein_g"] == 30


async def test_edit_entry_quantity_rejects_zero(client):
    food = await _create_food(client)
    r = await client.post(
        "/meals/entries", headers=HEADERS,
        json={"food_id": food["id"], "quantity_g": 100, "slot": "snack"},
    )
    entry_id = r.json()["id"]
    r = await client.patch(
        f"/meals/entries/{entry_id}", headers=HEADERS, json={"quantity_g": 0},
    )
    assert r.status_code == 422  # pydantic gt=0 validation


async def test_delete_entry(client):
    food = await _create_food(client)
    r = await client.post(
        "/meals/entries", headers=HEADERS,
        json={"food_id": food["id"], "quantity_g": 100, "slot": "snack"},
    )
    entry_id = r.json()["id"]
    r = await client.delete(f"/meals/entries/{entry_id}", headers=HEADERS)
    assert r.status_code == 204
    r = await client.get("/meals/today/totals", headers=HEADERS)
    assert r.json()["entry_count"] == 0


async def test_auth_required(client):
    r = await client.get("/foods/search?q=foo")
    assert r.status_code == 401
    r = await client.post("/meals/entries", json={"food_id": "x", "quantity_g": 1, "slot": "snack"})
    assert r.status_code == 401
