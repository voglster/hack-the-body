"""Coach endpoint tests.

We mock the Ollama HTTP call (we don't want CI talking to a real LLM).
"""
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx
import pytest
from bson import ObjectId as ObjectIdFromStr

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
    assert body["trigger"] == "manual"

    # The insight should have been persisted to coach_insights.
    saved = await mock_db["coach_insights"].count_documents({})
    assert saved == 1


async def test_recent_returns_persisted_insights(client, mock_db, fake_ollama_response):
    await _seed(mock_db)

    class _MockResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return fake_ollama_response

    async def _fake_post(_self, _url, json=None):
        del json
        return _MockResp()

    with patch.object(httpx.AsyncClient, "post", _fake_post):
        # Generate two insights so recent has something to return.
        await client.get("/coach/insight", headers=HEADERS)
        await client.get("/coach/insight", headers=HEADERS)

    r = await client.get("/coach/recent?limit=5", headers=HEADERS)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 2
    assert all("Sleep solid" in row["text"] for row in rows)


async def test_insight_uses_local_day_window_for_food_and_history(
    client, mock_db, fake_ollama_response,
):
    """Regression: a 9 PM Mountain user pointing the coach at /coach/insight
    should see *today's* food + steps + recent coach messages, not yesterday's.
    The browser passes the UTC bounds of its local day; we verify the prompt
    includes a `local_now` derived from those bounds and that yesterday's
    coach insight does NOT appear in the prompt history."""
    await _seed(mock_db)

    # Pretend "today" in the user's tz is 2026-04-26 Mountain (UTC-6).
    # Local midnight 2026-04-26 → 2026-04-26T06:00:00Z.
    day_start = datetime(2026, 4, 26, 6, 0, tzinfo=UTC)
    day_end = day_start + timedelta(days=1)

    # Seed a STALE coach insight from yesterday — this is the "you haven't
    # eaten" message that was leaking into today's prompts.
    await mock_db["coach_insights"].insert_one({
        "text": "You haven't eaten anything today. Eat something.",
        "trigger": "manual",
        "generated_at": day_start - timedelta(hours=2),  # 4 AM UTC = 10 PM Mountain yesterday
        "model": "test", "eval_ms": 0, "total_ms": 0, "context": {},
    })

    captured: dict = {}
    class _MockResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return fake_ollama_response
    async def _fake_post(_self, _url, json=None):
        captured["payload"] = json
        return _MockResp()

    with patch.object(httpx.AsyncClient, "post", _fake_post):
        r = await client.get(
            "/coach/insight",
            headers=HEADERS,
            params={"start": day_start.isoformat(), "end": day_end.isoformat()},
        )

    assert r.status_code == 200, r.text
    prompt = captured["payload"]["prompt"]
    # Yesterday's stale message must NOT have leaked into today's history.
    assert "You haven't eaten anything today" not in prompt
    # The new context fields must be present so the LLM has local-time signal.
    body = r.json()
    assert "local_now" in body["context"]
    assert "local_hour" in body["context"]
    assert "time_of_day" in body["context"]


async def test_insight_signals_no_food_logged_yet(client, mock_db, fake_ollama_response):
    """When zero food entries exist, the prompt must mark
    `food_logged_today: false` and the system prompt must instruct the
    model not to claim the user fasted."""
    await _seed(mock_db)
    captured: dict = {}
    class _MockResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return fake_ollama_response
    async def _fake_post(_self, _url, json=None):
        captured["payload"] = json
        return _MockResp()

    with patch.object(httpx.AsyncClient, "post", _fake_post):
        r = await client.get("/coach/insight", headers=HEADERS)

    assert r.status_code == 200
    prompt = captured["payload"]["prompt"]
    assert '"food_logged_today": false' in prompt
    assert '"entries": 0' in prompt
    # System prompt warns the model about this exact failure mode.
    assert "food_entries_today" in prompt
    assert "not that the client hasn't eaten" in prompt.lower() or \
           "NOT that the client hasn't eaten" in prompt


async def test_recent_filters_by_since(client, mock_db):
    """`/coach/recent?since=...` should only return insights at or after the
    given timestamp — used by the FE to scope to the local day."""
    base = datetime(2026, 4, 26, 6, 0, tzinfo=UTC)
    await mock_db["coach_insights"].insert_many([
        {"text": "yesterday", "generated_at": base - timedelta(hours=5),
         "trigger": "manual", "model": "t", "eval_ms": 0, "total_ms": 0, "context": {}},
        {"text": "today-am", "generated_at": base + timedelta(hours=2),
         "trigger": "manual", "model": "t", "eval_ms": 0, "total_ms": 0, "context": {}},
        {"text": "today-pm", "generated_at": base + timedelta(hours=14),
         "trigger": "manual", "model": "t", "eval_ms": 0, "total_ms": 0, "context": {}},
    ])
    r = await client.get("/coach/recent", headers=HEADERS, params={"since": base.isoformat()})
    assert r.status_code == 200
    rows = r.json()
    texts = [r["text"] for r in rows]
    assert "yesterday" not in texts
    assert "today-am" in texts and "today-pm" in texts


async def test_insight_response_includes_id(client, mock_db, fake_ollama_response):
    """Feedback needs to attach to a specific insight, so the response —
    and history rows — must carry the mongo id."""
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
    insight_id = r.json()["id"]
    assert insight_id

    r2 = await client.get("/coach/recent?limit=1", headers=HEADERS)
    assert r2.json()[0]["id"] == insight_id


async def test_feedback_round_trip(client, mock_db, fake_ollama_response):
    """Submit thumbs-down with a note, then read it back via /coach/feedback
    and confirm the joined insight text comes along (so the skill can read
    the prompt that earned the feedback)."""
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
    insight_id = r.json()["id"]

    r = await client.post(
        f"/coach/insights/{insight_id}/feedback",
        headers=HEADERS,
        json={"rating": "down", "note": "told me I fasted but I just hadn't logged"},
    )
    assert r.status_code == 201, r.text
    fb = r.json()
    assert fb["rating"] == "down"
    assert "fasted" in fb["note"]

    r = await client.get("/coach/feedback", headers=HEADERS)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["rating"] == "down"
    assert rows[0]["insight"]["id"] == insight_id
    assert rows[0]["insight"]["text"]  # joined prompt text is present


async def test_feedback_replaces_prior_and_archives_to_history(
    client, mock_db, fake_ollama_response,
):
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
    insight_id = r.json()["id"]

    await client.post(
        f"/coach/insights/{insight_id}/feedback",
        headers=HEADERS, json={"rating": "down", "note": "first take"},
    )
    await client.post(
        f"/coach/insights/{insight_id}/feedback",
        headers=HEADERS, json={"rating": "up", "note": "actually decent"},
    )
    # Only one current feedback per insight.
    assert await mock_db["coach_feedback"].count_documents(
        {"insight_id": ObjectIdFromStr(insight_id)},
    ) == 1
    # The earlier feedback is preserved as audit history.
    assert await mock_db["coach_feedback_history"].count_documents({}) == 1


async def test_feedback_clear_archives_then_empties(client, mock_db, fake_ollama_response):
    """`DELETE /coach/feedback` archives rows to coach_feedback_archive
    rather than hard-deleting, so the audit trail survives prompt-tuning."""
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
    iid = r.json()["id"]
    await client.post(
        f"/coach/insights/{iid}/feedback", headers=HEADERS,
        json={"rating": "down", "note": "bad take"},
    )
    assert await mock_db["coach_feedback"].count_documents({}) == 1

    r = await client.delete("/coach/feedback", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["archived"] == 1
    assert await mock_db["coach_feedback"].count_documents({}) == 0
    assert await mock_db["coach_feedback_archive"].count_documents({}) == 1
    archived = await mock_db["coach_feedback_archive"].find_one()
    assert archived["rating"] == "down"
    assert archived.get("cleared_at") is not None


async def test_feedback_404_on_unknown_insight(client):
    r = await client.post(
        "/coach/insights/000000000000000000000000/feedback",
        headers=HEADERS, json={"rating": "up"},
    )
    assert r.status_code == 404


async def test_feedback_400_on_bad_id(client):
    r = await client.post(
        "/coach/insights/not-an-oid/feedback",
        headers=HEADERS, json={"rating": "up"},
    )
    assert r.status_code == 400


async def test_insight_502_on_ollama_failure(client, mock_db):
    await _seed(mock_db)

    async def _broken(_self, _url, json=None):
        del json
        raise httpx.ConnectError("nope")

    with patch.object(httpx.AsyncClient, "post", _broken):
        r = await client.get("/coach/insight", headers=HEADERS)

    assert r.status_code == 502
    assert "coach LLM unavailable" in r.json()["detail"]
