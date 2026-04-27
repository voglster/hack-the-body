"""Coach endpoint tests.

We mock the Ollama HTTP call (we don't want CI talking to a real LLM).
"""
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import httpx
import pytest
from bson import ObjectId as ObjectIdFromStr

from app.models.metrics import HRV, Sleep, Weight
from app.services.coach import SYSTEM_PROMPT
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


async def test_insight_carries_water_total_separate_from_food(
    client, mock_db, fake_ollama_response,
):
    """Water entries are tagged food_name='Water' and zero macros — they
    must not inflate `entries` or macro totals, and they must surface
    as `water_oz` in food_totals so the coach can comment on hydration."""
    await _seed(mock_db)
    # Provision the Water food + log 32 oz across two pours.
    food = await client.post("/foods", headers=HEADERS, json={
        "name": "Water", "category": "drink", "serving_g": 236.6,
        "per_serving": {}, "source": "builtin",
    })
    water_id = food.json()["id"]
    for oz in (16, 16):
        await client.post("/meals/entries", headers=HEADERS, json={
            "food_id": water_id,
            "quantity_g": oz * 29.5735,
            "slot": "snack",
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
        await client.get("/coach/insight", headers=HEADERS)

    prompt = captured["payload"]["prompt"]
    assert '"water_oz": 32.0' in prompt
    # And water didn't get counted as food entries.
    assert '"entries": 0' in prompt
    assert '"food_logged_today": false' in prompt


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


async def test_insight_includes_targets_in_prompt(client, mock_db, fake_ollama_response):
    """If the user has set targets, they show up in the prompt as the
    `targets` block of context. This is what lets the model say
    '1,500 / 2,200 cal' instead of inventing a baseline."""
    await _seed(mock_db)
    await client.put(
        "/profile/targets", headers=HEADERS,
        json={"daily_calories": 2200, "daily_protein_g": 180},
    )

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
    assert '"targets":' in prompt
    assert '"daily_calories": 2200' in prompt
    assert '"daily_protein_g": 180' in prompt
    # And `step_goal_override` is there as null since it wasn't set.
    assert '"step_goal_override": null' in prompt


async def test_system_prompt_allows_action_optional():
    """User feedback: not every reply needs an action. SYSTEM_PROMPT
    must let the model skip the action when nothing's off-track."""
    lowered = SYSTEM_PROMPT.lower()
    assert "only if" in lowered
    assert "off-track" in lowered or "off track" in lowered
    assert "do not invent action" in lowered


async def test_insight_persists_full_prompt_inputs(
    client, mock_db, fake_ollama_response,
):
    """Regression: when a bad output happens, the review tool needs to
    answer "what was the model looking at?" — so we persist food_totals,
    history_snapshot, the rendered prompt, and the active system prompt.
    Pre-fix, only `context` was saved, leaving food_totals invisible to
    the review path."""
    await _seed(mock_db)
    # Seed a prior insight so history_snapshot is non-empty.
    await mock_db["coach_insights"].insert_one({
        "text": "earlier today: HRV low.",
        "trigger": "manual",
        "generated_at": datetime.now(UTC) - timedelta(hours=2),
        "model": "test", "eval_ms": 0, "total_ms": 0, "context": {},
    })

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
    saved = await mock_db["coach_insights"].find_one({"_id": ObjectIdFromStr(iid)})

    assert saved.get("food_totals") is not None
    assert "food_logged_today" in saved["food_totals"]
    assert isinstance(saved.get("history_snapshot"), list)
    assert saved.get("prompt") and "Latest data:" in saved["prompt"]
    assert saved.get("system_prompt") and "no-nonsense" in saved["system_prompt"]

    # And the feedback join surfaces them so tools/coach_feedback.py show works.
    await client.post(
        f"/coach/insights/{iid}/feedback", headers=HEADERS,
        json={"rating": "down", "note": "catabolic talk again"},
    )
    rows = (await client.get("/coach/feedback", headers=HEADERS)).json()
    ins = rows[0]["insight"]
    assert ins["food_totals"] is not None
    assert ins["prompt"] is not None
    assert ins["system_prompt"] is not None
    assert isinstance(ins["history_snapshot"], list)


async def test_system_prompt_forbids_clinical_alarmism():
    """The string-level guard is the cheapest way to verify the new
    anti-alarmism guardrails landed in the prompt — if a future edit
    drops them, this test fails loudly."""
    lowered = SYSTEM_PROMPT.lower()
    for forbidden_concept in ("catabolic", "starving", "metabolic collapse"):
        assert forbidden_concept in lowered, f"missing guard against {forbidden_concept!r}"
    assert "scold" in lowered or "lecture" in lowered or "do not use phrases" in lowered


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


async def test_insights_clear_archives_then_empties(client, mock_db, fake_ollama_response):
    """`DELETE /coach/insights` archives rows so the next coach prompt
    doesn't include outputs from the old (now-fixed) prompt as part of
    its `recent_coach_messages` history."""
    await _seed(mock_db)

    class _MockResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return fake_ollama_response
    async def _fake_post(_self, _url, json=None):
        del json
        return _MockResp()

    with patch.object(httpx.AsyncClient, "post", _fake_post):
        await client.get("/coach/insight", headers=HEADERS)
        await client.get("/coach/insight", headers=HEADERS)
    assert await mock_db["coach_insights"].count_documents({}) == 2

    r = await client.delete("/coach/insights", headers=HEADERS)
    assert r.status_code == 200
    assert r.json()["archived"] == 2
    assert await mock_db["coach_insights"].count_documents({}) == 0
    assert await mock_db["coach_insights_archive"].count_documents({}) == 2
    archived = await mock_db["coach_insights_archive"].find_one()
    assert archived.get("archived_at") is not None
    assert archived.get("original_id") is not None  # original _id carried over


async def test_insights_clear_with_before_only_archives_old(client, mock_db):
    """`?before=...` lets you keep newer insights (e.g. ones generated
    after the prompt was fixed) while archiving the older ones."""
    base = datetime(2026, 4, 26, 0, 0, tzinfo=UTC)
    await mock_db["coach_insights"].insert_many([
        {"text": "old", "generated_at": base, "trigger": "manual",
         "model": "t", "eval_ms": 0, "total_ms": 0, "context": {}},
        {"text": "newer", "generated_at": base + timedelta(days=2),
         "trigger": "manual", "model": "t", "eval_ms": 0, "total_ms": 0, "context": {}},
    ])
    cutoff = (base + timedelta(days=1)).isoformat()
    r = await client.delete(
        "/coach/insights", headers=HEADERS, params={"before": cutoff},
    )
    assert r.status_code == 200
    assert r.json()["archived"] == 1
    remaining = [d async for d in mock_db["coach_insights"].find()]
    assert len(remaining) == 1
    assert remaining[0]["text"] == "newer"


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
