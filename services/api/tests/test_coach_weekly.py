"""Weekly review tests — Ollama call mocked, mongo populated with 7d of data."""
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx
import pytest

from app.models.metrics import HRV, DailySummary, Sleep, Weight
from app.services.metrics_repo import MetricsRepo

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture
def fake_weekly_response():
    return {
        "model": "gpt-oss:120b",
        "response": (
            "**The week in one sentence.** Solid sleep, lagging steps.\n"
            "**Wins** — slept 7.2h avg.\n"
            "**Misses** — 8,400 step avg vs 12k goal.\n"
            "**Pattern** — late food on low-HRV days.\n"
            "**Next week** — 10k steps, 30min walk after dinner, weigh daily."
        ),
        "eval_duration": 30_000_000_000,
        "total_duration": 60_000_000_000,
    }


async def _seed_week(mock_db):
    repo = MetricsRepo(mock_db)
    base = datetime.now(UTC) - timedelta(days=6)
    for i in range(7):
        ts = base + timedelta(days=i)
        await repo.insert_sleep(Sleep(
            ts=ts, duration_s=25_200 + i * 100, deep_s=3600, rem_s=5400,
            light_s=15000, awake_s=1200, score=75 + i,
            source="garmin", source_id=f"s:{i}",
        ))
        await repo.insert_hrv(HRV(
            ts=ts, rmssd_ms=30.0 + i, source="garmin", source_id=f"h:{i}",
        ))
        await repo.insert_weight(Weight(
            ts=ts, kg=109.0 - i * 0.1, source="garmin", source_id=f"w:{i}",
        ))
        await repo.insert_daily_summary(DailySummary(
            ts=ts, steps=8000 + i * 200, step_goal=12000,
            source="garmin", source_id=f"d:{i}",
        ))


async def test_weekly_requires_auth(client):
    r = await client.get("/coach/weekly")
    assert r.status_code == 401


async def test_weekly_runs_and_persists(client, mock_db, fake_weekly_response):
    await _seed_week(mock_db)

    class _MockResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return fake_weekly_response

    async def _fake_post(_self, _url, **_kw):
        return _MockResp()

    with patch.object(httpx.AsyncClient, "post", _fake_post):
        r = await client.get("/coach/weekly", headers=HEADERS)

    assert r.status_code == 200, r.text
    body = r.json()
    assert "Wins" in body["text"]
    assert body["model"] == "gpt-oss:120b"
    assert body["trigger"] == "weekly-manual"

    saved = await mock_db["coach_insights"].count_documents({"trigger": "weekly-manual"})
    assert saved == 1


async def test_weekly_502_on_ollama_failure(client, mock_db):
    await _seed_week(mock_db)

    async def _broken(_self, _url, **_kw):
        raise httpx.ConnectError("nope")

    with patch.object(httpx.AsyncClient, "post", _broken):
        r = await client.get("/coach/weekly", headers=HEADERS)

    assert r.status_code == 502
    assert "weekly coach LLM unavailable" in r.json()["detail"]
