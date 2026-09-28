"""Paste-in food parsing — Ollama call mocked."""
from unittest.mock import patch

import httpx

from app.services.food_parser import (
    _extract_json_array,
    parse_food_text,
)
from tests.conftest import llm_body

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
        def json(self): return llm_body(SAMPLE_RESPONSE)

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
