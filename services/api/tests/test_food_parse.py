"""Paste-in food parsing — Ollama call mocked."""
from unittest.mock import patch

import httpx

from app.services.food_parser import (
    ParsedItem,
    _extract_json_array,
    parse_food_text,
)

H = {"X-API-Key": "test-key"}

SAMPLE_RESPONSE = """[
  {"name": "Crepe Shell", "servings": 1, "calories": 250},
  {"name": "Scrambled Eggs", "servings": 2, "calories": 150},
  {"name": "Smoked Salmon (2oz)", "servings": 1, "calories": 80,
   "protein_g": 14}
]"""


def test_extract_json_array_strips_prose():
    text = 'Sure! Here it is:\n```json\n[{"name": "Eggs"}]\n```\nDone.'
    out = _extract_json_array(text)
    assert out == [{"name": "Eggs"}]


def test_extract_json_array_handles_trailing_comma():
    text = '[{"name": "x",}, {"name": "y",},]'
    out = _extract_json_array(text)
    assert len(out) == 2


async def test_parse_food_text_returns_items(settings):
    class _R:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return {"response": SAMPLE_RESPONSE}

    async def _fake_post(_self, _url, **_kw):
        return _R()

    with patch.object(httpx.AsyncClient, "post", _fake_post):
        items = await parse_food_text(settings, "anything")

    names = [i.name for i in items]
    assert "Crepe Shell" in names
    assert "Scrambled Eggs" in names
    eggs = next(i for i in items if i.name == "Scrambled Eggs")
    assert eggs.servings == 2
    assert eggs.calories == 150


async def test_log_parsed_creates_foods_and_entries(client, mock_db):
    parsed = [
        {"name": "Crepe", "servings": 1, "calories": 250, "protein_g": 8},
        {"name": "Eggs", "servings": 2, "calories": 150, "protein_g": 12},
    ]
    r = await client.post(
        "/foods/parse/log",
        headers=H,
        json={"items": parsed, "slot": "lunch"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["count"] == 2
    assert len(body["entries"]) == 2

    # Both foods landed with source='paste' and there are 2 meal entries.
    assert await mock_db["foods"].count_documents({"source": "paste"}) == 2
    assert await mock_db["meal_entries"].count_documents({"slot": "lunch"}) == 2

    # Today's totals should reflect the supplied macros.
    r = await client.get("/meals/today/totals", headers=H)
    body = r.json()
    assert body["totals"]["calories"] == 400.0
    assert body["totals"]["protein_g"] == 20.0


async def test_parse_endpoint_502_on_llm_failure(client):
    # Patch the service function directly so we don't intercept the test
    # client's own httpx call to FastAPI.
    async def _boom(_settings, _text):
        raise httpx.ConnectError("nope")

    with patch("app.routers.foods.parse_food_text", _boom):
        r = await client.post("/foods/parse", headers=H, json={"text": "x"})

    assert r.status_code == 502
    assert "parser unavailable" in r.json()["detail"]


async def test_parse_endpoint_returns_items(client):
    async def _stub(_settings, _text):
        return [
            ParsedItem(name="Crepe Shell", calories=250),
            ParsedItem(name="Scrambled Eggs", servings=2, calories=150),
        ]

    with patch("app.routers.foods.parse_food_text", _stub):
        r = await client.post(
            "/foods/parse", headers=H, json={"text": "lunch breakdown"},
        )

    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 2
    assert items[0]["name"] == "Crepe Shell"


async def test_parse_requires_auth(client):
    r = await client.post("/foods/parse", json={"text": "x"})
    assert r.status_code == 401
    r = await client.post("/foods/parse/log", json={"items": []})
    assert r.status_code == 401
    r = await client.post(
        "/foods/parse/feedback",
        json={"text": "x", "parsed": []},
    )
    assert r.status_code == 401


async def test_parse_feedback_stores_report(client, mock_db):
    body = {
        "text": "Crepe Shell: 250\nRandom Latte: 110",
        "parsed": [
            {"name": "Crepe Shell", "calories": 250},
            {"name": "Random Latte", "calories": 110},
        ],
        "corrected": [
            {"name": "Crepe Shell", "calories": 250},
            {"name": "Almond Milk Latte", "calories": 110},
        ],
        "note": "got the latte name wrong — should know almond milk lattes",
    }
    r = await client.post("/foods/parse/feedback", headers=H, json=body)
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["stored"] is True
    assert out["id"]

    saved = await mock_db["parse_feedback"].find_one({})
    assert saved is not None
    assert saved["text"].startswith("Crepe Shell")
    assert saved["note"].startswith("got the latte")
    assert len(saved["parsed"]) == 2
    assert len(saved["corrected"]) == 2
