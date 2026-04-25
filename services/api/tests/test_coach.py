"""Coach endpoint tests.

We mock the Ollama HTTP call (we don't want CI talking to a real LLM).
"""
from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest

from app.models.metrics import HRV, Sleep, Weight
from app.services.metrics_repo import MetricsRepo

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture
def fake_ollama_response():
    """An object shaped like httpx.Response.json() output from Ollama."""
    return {
        "model": "glm-4.7-flash:latest",
        "response": "Sleep solid. HRV low — back off intensity. Walk 30min now.",
        "eval_count": 50,
        "eval_duration": 2_000_000_000,
        "total_duration": 4_000_000_000,
    }


async def _seed(mock_db):
    repo = MetricsRepo(mock_db)
    await repo.insert_sleep(Sleep(
        ts=datetime.now(UTC), duration_s=27000, deep_s=3600, rem_s=5400,
        light_s=16000, awake_s=2000, score=80,
        source="garmin", source_id="s:1",
    ))
    await repo.insert_hrv(HRV(
        ts=datetime.now(UTC), rmssd_ms=33.0,
        source="garmin", source_id="h:1",
    ))
    await repo.insert_weight(Weight(
        ts=datetime.now(UTC), kg=108.9,
        source="garmin", source_id="w:1",
    ))


async def test_insight_requires_auth(client):
    r = await client.get("/coach/insight")
    assert r.status_code == 401


async def test_insight_returns_text_and_metadata(client, mock_db, fake_ollama_response):
    await _seed(mock_db)

    class _MockResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return fake_ollama_response

    async def _fake_post(_self, _url, json=None):
        del json
        return _MockResp()

    with patch.object(httpx.AsyncClient, "post", _fake_post):
        r = await client.get("/coach/insight", headers=HEADERS)

    assert r.status_code == 200
    body = r.json()
    assert "Sleep solid" in body["text"]
    assert body["model"] == "glm-4.7-flash:latest"
    assert body["eval_ms"] == 2000
    assert body["total_ms"] == 4000
    assert body["context"]["sleep"]["duration_s"] == 27000
    assert body["context"]["hrv"]["rmssd_ms"] == 33.0


async def test_insight_502_on_ollama_failure(client, mock_db):
    await _seed(mock_db)

    async def _broken(_self, _url, json=None):
        del json
        raise httpx.ConnectError("nope")

    with patch.object(httpx.AsyncClient, "post", _broken):
        r = await client.get("/coach/insight", headers=HEADERS)

    assert r.status_code == 502
    assert "coach LLM unavailable" in r.json()["detail"]
