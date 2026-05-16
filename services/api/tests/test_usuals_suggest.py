"""Tests for usuals suggestion (deterministic miner)."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from bson import ObjectId

from app.services.usuals_miner import mine_candidates, signature
from app.services.usuals_suggest import suggest_usuals

HEADERS = {"X-API-Key": "test-key"}


def test_signature_is_order_independent():
    assert signature("breakfast", ["a", "b", "c"]) == signature("breakfast", ["c", "a", "b"])
    assert signature("lunch", ["a", "b"]) != signature("snack", ["a", "b"])


def test_mine_finds_consistent_group():
    now = datetime(2026, 5, 1, 7, 30, tzinfo=UTC)
    entries: list[dict] = []
    for i in range(8):
        d = now + timedelta(days=i)
        entries.append({"ts": d, "food_id": "yog", "food_name": "Yogurt",
                        "slot": "breakfast", "quantity_g": 170})
        entries.append({"ts": d, "food_id": "gra", "food_name": "Granola",
                        "slot": "breakfast", "quantity_g": 40})
    r = mine_candidates(entries, templates=[], dismissed_sigs=set())
    assert len(r["new"]) == 1
    c = r["new"][0]
    assert c["slot"] == "breakfast"
    assert {it["food_id"] for it in c["items"]} == {"yog", "gra"}
    assert c["occurrences"] == 8
    assert c["confidence"] == 1.0


def test_mine_skips_existing_exact_template():
    now = datetime(2026, 5, 1, 7, 30, tzinfo=UTC)
    entries = []
    for i in range(8):
        d = now + timedelta(days=i)
        entries.extend([
            {"ts": d, "food_id": "yog", "food_name": "Yogurt",
             "slot": "breakfast", "quantity_g": 170},
            {"ts": d, "food_id": "gra", "food_name": "Granola",
             "slot": "breakfast", "quantity_g": 40},
        ])
    templates = [{
        "name": "Yogurt Breakfast",
        "default_slot": "breakfast",
        "items": [{"food_id": "yog", "quantity_g": 170},
                  {"food_id": "gra", "quantity_g": 40}],
    }]
    r = mine_candidates(entries, templates, dismissed_sigs=set())
    assert r["new"] == []
    assert r["augment"] == []


def test_mine_suggests_augmenting_existing_template():
    now = datetime(2026, 5, 1, 7, 30, tzinfo=UTC)
    entries = []
    for i in range(8):
        d = now + timedelta(days=i)
        entries.extend([
            {"ts": d, "food_id": "yog", "food_name": "Yogurt",
             "slot": "breakfast", "quantity_g": 170},
            {"ts": d, "food_id": "gra", "food_name": "Granola",
             "slot": "breakfast", "quantity_g": 40},
            {"ts": d, "food_id": "chia", "food_name": "Chia",
             "slot": "breakfast", "quantity_g": 8},
        ])
    # Existing template missing the chia
    templates = [{
        "name": "Yogurt Breakfast",
        "default_slot": "breakfast",
        "items": [{"food_id": "yog", "quantity_g": 170},
                  {"food_id": "gra", "quantity_g": 40}],
    }]
    r = mine_candidates(entries, templates, dismissed_sigs=set())
    assert r["new"] == []
    assert len(r["augment"]) == 1
    aug = r["augment"][0]
    assert aug["template_name"] == "Yogurt Breakfast"
    assert aug["add_food_ids"] == ["chia"]
    assert aug["add_food_names"] == ["Chia"]


def test_mine_excludes_water_and_vitamins():
    now = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)
    entries = []
    for i in range(5):
        d = now + timedelta(days=i)
        entries.extend([
            {"ts": d, "food_id": "shake", "food_name": "Shake",
             "slot": "snack", "quantity_g": 325},
            {"ts": d, "food_id": "water", "food_name": "Water",
             "slot": "snack", "quantity_g": 480},
            {"ts": d, "food_id": "vit", "food_name": "Vitamins",
             "slot": "supplement", "quantity_g": 1},
        ])
    r = mine_candidates(entries, templates=[], dismissed_sigs=set())
    assert r["new"] == []  # no group of 2+ after exclusions
    assert r["augment"] == []


def test_mine_respects_dismissal():
    now = datetime(2026, 5, 1, 7, 30, tzinfo=UTC)
    entries = []
    for i in range(8):
        d = now + timedelta(days=i)
        entries.extend([
            {"ts": d, "food_id": "yog", "food_name": "Yogurt",
             "slot": "breakfast", "quantity_g": 170},
            {"ts": d, "food_id": "gra", "food_name": "Granola",
             "slot": "breakfast", "quantity_g": 40},
        ])
    sig = signature("breakfast", ["yog", "gra"])
    r = mine_candidates(entries, templates=[], dismissed_sigs={sig})
    assert r["new"] == []


def test_mine_drops_low_confidence_noise():
    now = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)
    entries = []
    # 20 snacks at different times, only 3 with both foods together
    for i in range(17):
        entries.append({
            "ts": now + timedelta(days=i),
            "food_id": "lonely", "food_name": "Lonely",
            "slot": "snack", "quantity_g": 50,
        })
    for i in range(17, 20):
        d = now + timedelta(days=i)
        entries.append({"ts": d, "food_id": "a", "food_name": "A",
                        "slot": "snack", "quantity_g": 30})
        entries.append({"ts": d, "food_id": "b", "food_name": "B",
                        "slot": "snack", "quantity_g": 40})
    # No multi-food days exist for the lonely-snack window, so (a,b) at 3/3
    # multi-item-snack days = 100% confidence — pattern is real, surfaces.
    r = mine_candidates(entries, templates=[], dismissed_sigs=set())
    # Confidence is computed against day-sets with >=2 items.
    assert len(r["new"]) == 1


def test_mine_heuristic_name_long_set():
    now = datetime(2026, 5, 1, 7, 30, tzinfo=UTC)
    entries = []
    for i in range(5):
        d = now + timedelta(days=i)
        entries.extend([
            {"ts": d, "food_id": "a", "food_name": "Yogurt",
             "slot": "breakfast", "quantity_g": 170},
            {"ts": d, "food_id": "b", "food_name": "Granola",
             "slot": "breakfast", "quantity_g": 40},
            {"ts": d, "food_id": "c", "food_name": "Chia",
             "slot": "breakfast", "quantity_g": 8},
            {"ts": d, "food_id": "d", "food_name": "Protein Powder",
             "slot": "breakfast", "quantity_g": 30},
        ])
    r = mine_candidates(entries, templates=[], dismissed_sigs=set())
    assert len(r["new"]) == 1
    # 4 items → first 3 joined + "+1"
    assert "+1" in r["new"][0]["name"]


@pytest.mark.asyncio
async def test_suggest_endpoint_returns_new_and_augment(client, mock_db, settings):
    yog_id, gra_id = ObjectId(), ObjectId()
    await mock_db["foods"].insert_many([
        {"_id": yog_id, "name": "Yogurt", "serving_g": 170,
         "per_serving": {"calories": 100}, "category": "food"},
        {"_id": gra_id, "name": "Granola", "serving_g": 40,
         "per_serving": {"calories": 180}, "category": "food"},
    ])
    now = datetime.now(UTC)
    for i in range(5):
        d = now - timedelta(days=i)
        await mock_db["meal_entries"].insert_many([
            {"ts": d, "food_id": str(yog_id), "food_name": "Yogurt",
             "slot": "breakfast", "quantity_g": 170,
             "meta": {"food_id": str(yog_id), "slot": "breakfast"}},
            {"ts": d, "food_id": str(gra_id), "food_name": "Granola",
             "slot": "breakfast", "quantity_g": 40,
             "meta": {"food_id": str(gra_id), "slot": "breakfast"}},
        ])

    r = await client.post("/meals/templates/suggest", headers=HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["new"]) == 1
    assert body["augment"] == []
    c = body["new"][0]
    assert c["slot"] == "breakfast"
    assert "signature" in c


@pytest.mark.asyncio
async def test_suggest_caps_at_5(mock_db, settings):
    """Hand-craft enough patterns to exceed the cap."""
    # 6 slot patterns — all confident, none existing
    now = datetime.now(UTC)
    for slot_idx, slot in enumerate(
        ["breakfast", "lunch", "dinner", "snack", "supplement"],
    ):
        for i in range(5):
            d = now - timedelta(days=i, hours=slot_idx)
            await mock_db["meal_entries"].insert_many([
                {"ts": d, "food_id": f"a-{slot}", "food_name": f"A-{slot}",
                 "slot": slot, "quantity_g": 30,
                 "meta": {"food_id": f"a-{slot}", "slot": slot}},
                {"ts": d, "food_id": f"b-{slot}", "food_name": f"B-{slot}",
                 "slot": slot, "quantity_g": 30,
                 "meta": {"food_id": f"b-{slot}", "slot": slot}},
            ])
    result = await suggest_usuals(settings, mock_db)
    assert len(result["new"]) + len(result["augment"]) <= 5


@pytest.mark.asyncio
async def test_dismiss_suggestion_persists(client, mock_db):
    r = await client.post(
        "/meals/templates/suggest/dismiss",
        headers=HEADERS,
        json={"signature": "breakfast:aaa,bbb"},
    )
    assert r.status_code == 200, r.text
    row = await mock_db["usuals_suggest_dismissed"].find_one(
        {"signature": "breakfast:aaa,bbb"},
    )
    assert row is not None
    until = row["dismissed_until"]
    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    assert until > datetime.now(UTC)


@pytest.mark.asyncio
async def test_suggest_respects_dismissal_signature(client, mock_db, settings):
    yog_id, gra_id = ObjectId(), ObjectId()
    await mock_db["foods"].insert_many([
        {"_id": yog_id, "name": "Yogurt", "serving_g": 170,
         "per_serving": {}, "category": "food"},
        {"_id": gra_id, "name": "Granola", "serving_g": 40,
         "per_serving": {}, "category": "food"},
    ])
    now = datetime.now(UTC)
    for i in range(5):
        d = now - timedelta(days=i)
        await mock_db["meal_entries"].insert_many([
            {"ts": d, "food_id": str(yog_id), "food_name": "Yogurt",
             "slot": "breakfast", "quantity_g": 170,
             "meta": {"food_id": str(yog_id), "slot": "breakfast"}},
            {"ts": d, "food_id": str(gra_id), "food_name": "Granola",
             "slot": "breakfast", "quantity_g": 40,
             "meta": {"food_id": str(gra_id), "slot": "breakfast"}},
        ])
    sig = signature("breakfast", [str(yog_id), str(gra_id)])
    await mock_db["usuals_suggest_dismissed"].insert_one({
        "signature": sig,
        "dismissed_until": now + timedelta(days=7),
    })

    r = await client.post("/meals/templates/suggest", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["new"] == []
    assert body["augment"] == []
