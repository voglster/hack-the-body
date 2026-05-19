from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.services.coach.brief import (
    BRIEF_SYSTEM_PROMPT,
    KIOSK_SYSTEM_PROMPT,
    Insight,
    generate_insight,
    recent_insights,
    save_insight,
)

_JSON_RESPONSE = (
    '{"text": "Lights out at {{lights_out}}.", '
    '"anchors": {"lights_out": "2026-05-19T22:00:00-05:00"}}'
)


@pytest.mark.asyncio
async def test_save_and_recent_round_trip_anchors(mock_db):
    insight = Insight(
        text="Lights out at {{lights_out}}.",
        model="m",
        eval_ms=0,
        total_ms=0,
        generated_at=datetime.now(UTC),
        context={},
        trigger="manual",
        anchors={"lights_out": "2026-05-19T22:00:00-05:00"},
    )
    insight.id = await save_insight(mock_db, insight)
    rows = await recent_insights(mock_db, limit=5)
    assert rows[0]["anchors"] == {"lights_out": "2026-05-19T22:00:00-05:00"}


def _make_fake_post(fake_resp: dict):
    async def fake_post(*_args, **_kwargs):
        m = AsyncMock()
        m.raise_for_status = lambda: None
        m.json = lambda: fake_resp
        return m
    return fake_post


@pytest.mark.asyncio
async def test_generate_insight_parses_anchors_from_json(mock_db, settings):
    fake_resp = {
        "response": _JSON_RESPONSE,
        "eval_duration": 0,
        "total_duration": 0,
    }
    with patch("app.services.coach.brief.httpx.AsyncClient") as mock_client:
        instance = mock_client.return_value.__aenter__.return_value
        instance.post = _make_fake_post(fake_resp)
        insight = await generate_insight(settings, mock_db, trigger="manual")
    assert insight.text == "Lights out at {{lights_out}}."
    assert insight.anchors == {"lights_out": "2026-05-19T22:00:00-05:00"}


@pytest.mark.asyncio
async def test_generate_insight_falls_back_when_json_invalid(mock_db, settings):
    fake_resp = {
        "response": "not json at all just prose",
        "eval_duration": 0,
        "total_duration": 0,
    }
    with patch("app.services.coach.brief.httpx.AsyncClient") as mock_client:
        instance = mock_client.return_value.__aenter__.return_value
        instance.post = _make_fake_post(fake_resp)
        insight = await generate_insight(settings, mock_db, trigger="manual")
    assert insight.text == "not json at all just prose"
    assert insight.anchors in ({}, None)


def test_brief_prompt_documents_anchors_contract():
    assert "{{lights_out}}" in BRIEF_SYSTEM_PROMPT or "{{name}}" in BRIEF_SYSTEM_PROMPT
    assert "anchors" in BRIEF_SYSTEM_PROMPT
    assert "in N minutes" in BRIEF_SYSTEM_PROMPT or "Never write" in BRIEF_SYSTEM_PROMPT


def test_kiosk_prompt_documents_anchors_field():
    assert "anchors" in KIOSK_SYSTEM_PROMPT
    assert "{{" in KIOSK_SYSTEM_PROMPT  # at least one placeholder example
