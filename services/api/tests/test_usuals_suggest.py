"""Tests for usuals suggestion (LLM-mocked)."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from app.services.usuals_suggest import (
    _build_user_prompt,
    _frequent_foods,
    _signature,
    _strip_fences,
)

HEADERS = {"X-API-Key": "test-key"}


def test_strip_fences_handles_json_block():
    assert _strip_fences("```json\n{\"a\":1}\n```") == '{"a":1}'
    assert _strip_fences("```\n{}\n```") == "{}"
    assert _strip_fences("{}") == "{}"


def test_signature_is_order_independent():
    s1 = _signature(["a", "b", "c"], "breakfast")
    s2 = _signature(["c", "a", "b"], "breakfast")
    assert s1 == s2
    assert _signature(["a", "b"], "lunch") != _signature(["a", "b"], "snack")


def test_frequent_foods_drops_lt_3():
    entries = [
        {"food_id": "a"}, {"food_id": "a"}, {"food_id": "a"},  # 3 → keep
        {"food_id": "b"}, {"food_id": "b"},                     # 2 → drop
        {"food_id": "c"},                                       # 1 → drop
    ]
    assert _frequent_foods(entries) == {"a"}


def test_build_user_prompt_includes_only_frequent_pairs():
    now = datetime(2026, 5, 1, 8, 0, tzinfo=UTC)
    entries = []
    # 4 mornings of (yogurt + granola) — both should appear
    for i in range(4):
        d = now + timedelta(days=i)
        entries.append({
            "ts": d, "food_id": "yog", "food_name": "Yogurt",
            "slot": "breakfast", "quantity_g": 170,
        })
        entries.append({
            "ts": d, "food_id": "gra", "food_name": "Granola",
            "slot": "breakfast", "quantity_g": 40,
        })
    # one-off: should be filtered
    entries.append({
        "ts": now, "food_id": "rare", "food_name": "Rare Thing",
        "slot": "snack", "quantity_g": 10,
    })
    prompt = _build_user_prompt(entries, templates=[], dismissed_signatures=set())
    assert "Yogurt" in prompt
    assert "Granola" in prompt
    assert "Rare Thing" not in prompt


@pytest.mark.asyncio
async def test_suggest_endpoint_returns_validated_payload(client, mock_db):
    # Seed a food + entries so the pipeline has signal
    from bson import ObjectId
    yog_id = ObjectId()
    gra_id = ObjectId()
    await mock_db["foods"].insert_many([
        {"_id": yog_id, "name": "Yogurt", "serving_g": 170,
         "per_serving": {"calories": 100}, "category": "food"},
        {"_id": gra_id, "name": "Granola", "serving_g": 40,
         "per_serving": {"calories": 180}, "category": "food"},
    ])
    now = datetime.now(UTC)
    docs = []
    for i in range(5):
        d = now - timedelta(days=i)
        docs.append({"ts": d, "food_id": str(yog_id), "food_name": "Yogurt",
                     "slot": "breakfast", "quantity_g": 170,
                     "meta": {"food_id": str(yog_id), "slot": "breakfast"}})
        docs.append({"ts": d, "food_id": str(gra_id), "food_name": "Granola",
                     "slot": "breakfast", "quantity_g": 40,
                     "meta": {"food_id": str(gra_id), "slot": "breakfast"}})
    await mock_db["meal_entries"].insert_many(docs)

    fake_response = {
        "message": {"content": json.dumps({"suggestions": [
            {
                "name": "Yogurt Breakfast",
                "slot": "breakfast",
                "items": [
                    {"food_id": str(yog_id), "quantity_g": 170},
                    {"food_id": str(gra_id), "quantity_g": 40},
                ],
                "rationale": "logged together 5 of last 5 mornings",
            },
        ]})},
    }

    async def _fake_call(settings, prompt):  # noqa: ARG001
        return json.loads(fake_response["message"]["content"])

    with patch("app.services.usuals_suggest._call_ollama", _fake_call):
        r = await client.post("/meals/templates/suggest", headers=HEADERS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["suggestions"]) == 1
    s = body["suggestions"][0]
    assert s["name"] == "Yogurt Breakfast"
    assert s["slot"] == "breakfast"
    assert len(s["items"]) == 2
    assert "signature" in s


@pytest.mark.asyncio
async def test_suggest_filters_unknown_food_ids(client, mock_db):
    from bson import ObjectId
    yog_id = ObjectId()
    await mock_db["foods"].insert_one({
        "_id": yog_id, "name": "Yogurt", "serving_g": 170,
        "per_serving": {"calories": 100}, "category": "food",
    })
    now = datetime.now(UTC)
    for i in range(3):
        await mock_db["meal_entries"].insert_one({
            "ts": now - timedelta(days=i), "food_id": str(yog_id),
            "food_name": "Yogurt", "slot": "breakfast", "quantity_g": 170,
            "meta": {"food_id": str(yog_id), "slot": "breakfast"},
        })

    fake_response = {
        "message": {"content": json.dumps({"suggestions": [
            {
                "name": "Bogus", "slot": "breakfast",
                "items": [
                    {"food_id": str(yog_id), "quantity_g": 170},
                    {"food_id": str(ObjectId()), "quantity_g": 50},  # unknown
                ],
                "rationale": "n/a",
            },
        ]})},
    }

    async def _fake_call(settings, prompt):  # noqa: ARG001
        return json.loads(fake_response["message"]["content"])

    with patch("app.services.usuals_suggest._call_ollama", _fake_call):
        r = await client.post("/meals/templates/suggest", headers=HEADERS)
    # Suggestion drops to 1 valid item → fewer than 2 → filtered out entirely
    assert r.status_code == 200
    assert r.json()["suggestions"] == []


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
    # mongomock strips tz; compare naive-vs-naive
    until = row["dismissed_until"]
    if until.tzinfo is None:
        until = until.replace(tzinfo=UTC)
    assert until > datetime.now(UTC)


@pytest.mark.asyncio
async def test_suggest_respects_dismissals(client, mock_db):
    from bson import ObjectId
    yog_id = ObjectId()
    gra_id = ObjectId()
    await mock_db["foods"].insert_many([
        {"_id": yog_id, "name": "Yogurt", "serving_g": 170,
         "per_serving": {"calories": 100}, "category": "food"},
        {"_id": gra_id, "name": "Granola", "serving_g": 40,
         "per_serving": {"calories": 180}, "category": "food"},
    ])
    now = datetime.now(UTC)
    for i in range(3):
        d = now - timedelta(days=i)
        await mock_db["meal_entries"].insert_many([
            {"ts": d, "food_id": str(yog_id), "food_name": "Yogurt",
             "slot": "breakfast", "quantity_g": 170,
             "meta": {"food_id": str(yog_id), "slot": "breakfast"}},
            {"ts": d, "food_id": str(gra_id), "food_name": "Granola",
             "slot": "breakfast", "quantity_g": 40,
             "meta": {"food_id": str(gra_id), "slot": "breakfast"}},
        ])

    sig = _signature([str(yog_id), str(gra_id)], "breakfast")
    await mock_db["usuals_suggest_dismissed"].insert_one({
        "signature": sig,
        "dismissed_until": now + timedelta(days=7),
    })

    fake_response = {
        "message": {"content": json.dumps({"suggestions": [
            {
                "name": "Yogurt Breakfast", "slot": "breakfast",
                "items": [
                    {"food_id": str(yog_id), "quantity_g": 170},
                    {"food_id": str(gra_id), "quantity_g": 40},
                ],
                "rationale": "x",
            },
        ]})},
    }

    async def _fake_call(settings, prompt):  # noqa: ARG001
        return json.loads(fake_response["message"]["content"])

    with patch("app.services.usuals_suggest._call_ollama", _fake_call):
        r = await client.post("/meals/templates/suggest", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["suggestions"] == []


@pytest.mark.asyncio
async def test_suggest_handles_ollama_failure(client, mock_db):
    from bson import ObjectId
    yog_id = ObjectId()
    await mock_db["foods"].insert_one({
        "_id": yog_id, "name": "Yogurt", "serving_g": 170,
        "per_serving": {"calories": 100}, "category": "food",
    })
    now = datetime.now(UTC)
    for i in range(3):
        await mock_db["meal_entries"].insert_one({
            "ts": now - timedelta(days=i), "food_id": str(yog_id),
            "food_name": "Yogurt", "slot": "breakfast", "quantity_g": 170,
            "meta": {"food_id": str(yog_id), "slot": "breakfast"},
        })

    async def _fail(settings, prompt):  # noqa: ARG001
        raise RuntimeError("ollama down")

    with patch("app.services.usuals_suggest._call_ollama", _fail):
        r = await client.post("/meals/templates/suggest", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert body["suggestions"] == []
    assert "error" in body
