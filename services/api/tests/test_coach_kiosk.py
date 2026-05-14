"""Tests for /coach/kiosk endpoint.

The kiosk gets a glance-line rendered through KIOSK_SYSTEM_PROMPT, and
the result is cached for 15 min so 60s kiosk polling doesn't hammer
the LLM.
"""
from unittest.mock import patch

import httpx
import pytest

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture
def fake_ollama_response():
    return {
        "model": "glm-4.7-flash:latest",
        "response": "Behind on steps. 15-min walk now.",
        "eval_count": 10,
        "eval_duration": 1_000_000_000,
        "total_duration": 2_000_000_000,
    }


def _make_fake_post(mock_response: dict, counter: list[int]):
    class _MockResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return mock_response

    async def _fake_post(_self, _url, json=None):
        del json
        counter[0] += 1
        return _MockResp()
    return _fake_post


async def test_kiosk_returns_insight(client, fake_ollama_response):
    counter = [0]
    with patch.object(httpx.AsyncClient, "post", _make_fake_post(fake_ollama_response, counter)):
        r = await client.get(
            "/coach/kiosk?start=2026-05-14T06:00:00Z&end=2026-05-15T06:00:00Z",
            headers=HEADERS,
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["trigger"] == "kiosk"
    assert body["text"].startswith("Behind on steps")


async def test_kiosk_caches_within_ttl(client, fake_ollama_response):
    counter = [0]
    with patch.object(httpx.AsyncClient, "post", _make_fake_post(fake_ollama_response, counter)):
        r1 = await client.get(
            "/coach/kiosk?start=2026-05-14T06:00:00Z&end=2026-05-15T06:00:00Z",
            headers=HEADERS,
        )
        r2 = await client.get(
            "/coach/kiosk?start=2026-05-14T06:00:00Z&end=2026-05-15T06:00:00Z",
            headers=HEADERS,
        )
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]
    assert counter[0] == 1, f"expected 1 LLM call, got {counter[0]}"


async def test_kiosk_requires_auth(client):
    r = await client.get("/coach/kiosk")
    assert r.status_code == 401
