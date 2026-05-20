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


async def test_kiosk_parses_structured_json_response(client):
    counter = [0]
    structured = {
        "model": "glm-4.7-flash:latest",
        "response": (
            '{"verb": "EAT", "qualifier": "1,651 kcal by 7:00 PM", '
            '"urgency": "urgent", '
            '"coach": "Lunch happened. The log does not yet reflect this."}'
        ),
        "eval_count": 10,
        "eval_duration": 1_000_000_000,
        "total_duration": 2_000_000_000,
    }
    with patch.object(httpx.AsyncClient, "post", _make_fake_post(structured, counter)):
        r = await client.get(
            "/coach/kiosk?start=2026-05-14T06:00:00Z&end=2026-05-15T06:00:00Z",
            headers=HEADERS,
        )
    assert r.status_code == 200, r.text
    body = r.json()
    # With empty findings.attention (no DB seed), the server-side override
    # forces verb to CLEAR — that's tested in a dedicated test below. Here
    # we just verify the JSON parsing path surfaces the coach sentence.
    assert body["coach"].startswith("Lunch happened")


async def test_kiosk_forces_clear_when_findings_attention_empty(client):
    """Even when the LLM hallucinates an action verb, if findings.attention
    is empty (nothing actually needs doing right now) the server overrides
    to CLEAR. Prevents 'EAT' from showing on the wall after the user has
    logged plenty of food but is under their calorie target."""
    counter = [0]
    structured = {
        "model": "glm-4.7-flash:latest",
        "response": (
            '{"verb": "EAT", "qualifier": "200 kcal short", '
            '"urgency": "urgent", '
            '"coach": "Calories logged. Steps remain low."}'
        ),
        "eval_count": 10,
        "eval_duration": 1_000_000_000,
        "total_duration": 2_000_000_000,
    }
    with patch.object(httpx.AsyncClient, "post", _make_fake_post(structured, counter)):
        r = await client.get(
            "/coach/kiosk?start=2026-05-14T08:00:00Z&end=2026-05-15T08:00:00Z",
            headers=HEADERS,
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verb"] == "CLEAR"
    assert body["qualifier"] == ""
    assert body["urgency"] == "clear"
    # Coach line is preserved — the override only nukes the verb.
    assert body["coach"].startswith("Calories logged")


async def test_kiosk_falls_back_when_response_is_not_json(client):
    counter = [0]
    bad = {
        "model": "glm-4.7-flash:latest",
        "response": "just plain text",
        "eval_count": 10,
        "eval_duration": 1_000_000_000,
        "total_duration": 2_000_000_000,
    }
    with patch.object(httpx.AsyncClient, "post", _make_fake_post(bad, counter)):
        r = await client.get(
            "/coach/kiosk?start=2026-05-14T07:00:00Z&end=2026-05-15T07:00:00Z",
            headers=HEADERS,
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verb"] == "CLEAR"
    assert body["qualifier"] == ""
    assert body["urgency"] == "clear"
    assert body["coach"] == "just plain text"


@pytest.mark.asyncio
async def test_kiosk_serializes_anchors_field(client, monkeypatch):
    from datetime import UTC, datetime  # noqa: PLC0415

    from app.services.coach.brief import Insight  # noqa: PLC0415

    fake_json = (
        '{"verb": "WIND DOWN", "qualifier": "20 min left", '
        '"urgency": "action", "coach": "Lights out at {{lights_out}}.", '
        '"anchors": {"lights_out": "2026-05-19T22:00:00-05:00"}}'
    )
    stub = Insight(
        text=fake_json, model="m", eval_ms=0, total_ms=0,
        generated_at=datetime.now(UTC), context={"attention": ["lights_out"]},
        trigger="kiosk",
    )

    async def fake_gen(*_a, **_kw):
        return stub

    monkeypatch.setattr("app.routers.coach.generate_insight", fake_gen)
    r = await client.get("/coach/kiosk", headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    body = r.json()
    assert body["anchors"] == {"lights_out": "2026-05-19T22:00:00-05:00"}
    assert body["coach"] == "Lights out at {{lights_out}}."


@pytest.mark.asyncio
async def test_kiosk_includes_phase_fields(client, mock_db, monkeypatch):
    from datetime import UTC, datetime  # noqa: PLC0415

    from app.services.coach.brief import Insight  # noqa: PLC0415

    stub = Insight(
        text='{"verb":"CLEAR","qualifier":"","urgency":"clear","coach":"hi","anchors":{}}',
        model="m", eval_ms=0, total_ms=0,
        generated_at=datetime.now(UTC), context={"attention": []},
        trigger="kiosk",
    )

    async def fake_gen(*_a, **_kw):
        return stub

    monkeypatch.setattr("app.routers.coach.generate_insight", fake_gen)
    r = await client.get("/coach/kiosk", headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    body = r.json()
    assert "phase" in body
    assert body["phase"] in ("day", "wind-down", "late")
    assert "lights_out_at" in body
    assert "wind_down_mode" in body
    assert isinstance(body["wind_down_mode"], bool)


async def test_recent_excludes_kiosk_trigger_by_default(client, mock_db):
    """Kiosk insights store raw JSON in `text`; they must not appear in
    /coach/recent (which the dashboard CoachCard reads) or as history
    fed to the normal /coach/insight prompt."""
    from datetime import UTC, datetime
    await mock_db["coach_insights"].insert_many([
        {
            "text": "Solid morning. Keep going.",
            "model": "x", "eval_ms": 1, "total_ms": 1,
            "generated_at": datetime.now(UTC),
            "context": {}, "trigger": "manual",
        },
        {
            "text": '{"verb":"EAT","qualifier":"now","urgency":"urgent","coach":"hi"}',
            "model": "x", "eval_ms": 1, "total_ms": 1,
            "generated_at": datetime.now(UTC),
            "context": {}, "trigger": "kiosk",
        },
    ])
    r = await client.get("/coach/recent?limit=5", headers=HEADERS)
    assert r.status_code == 200
    rows = r.json()
    assert len(rows) == 1
    assert rows[0]["trigger"] == "manual"
