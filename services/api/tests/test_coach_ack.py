from datetime import UTC, datetime, timedelta

import pytest
from bson import ObjectId

from app.services.coach.brief import Insight, recent_insights, resolve_day_window, save_insight


@pytest.mark.asyncio
async def test_recent_insights_returns_acked_at(mock_db):
    insight = Insight(
        text="hello", model="m", eval_ms=0, total_ms=0,
        generated_at=datetime.now(UTC), context={}, trigger="manual",
    )
    insight.id = await save_insight(mock_db, insight)
    rows = await recent_insights(mock_db, limit=5)
    assert "acked_at" in rows[0]
    assert rows[0]["acked_at"] is None


def _oid(s: str) -> ObjectId:
    return ObjectId(s)


@pytest.mark.asyncio
async def test_ack_insight_by_id_sets_acked_at(client, mock_db):
    insight = Insight(
        text="hi", model="m", eval_ms=0, total_ms=0,
        generated_at=datetime.now(UTC), context={}, trigger="manual",
    )
    insight.id = await save_insight(mock_db, insight)

    r = await client.post(
        f"/coach/insights/{insight.id}/ack",
        headers={"X-API-Key": "test-key"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == insight.id
    assert body["acked_at"] is not None

    first_acked = body["acked_at"]
    r2 = await client.post(
        f"/coach/insights/{insight.id}/ack",
        headers={"X-API-Key": "test-key"},
    )
    assert r2.status_code == 200
    assert r2.json()["acked_at"] == first_acked


@pytest.mark.asyncio
async def test_ack_unknown_insight_returns_404(client):
    r = await client.post(
        "/coach/insights/507f1f77bcf86cd799439011/ack",
        headers={"X-API-Key": "test-key"},
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_ack_web_latest_picks_most_recent_manual_today(client, mock_db):
    start, end = resolve_day_window(None, None)
    older = Insight(
        text="older", model="m", eval_ms=0, total_ms=0,
        generated_at=start + timedelta(hours=1), context={}, trigger="manual",
    )
    newer = Insight(
        text="newer", model="m", eval_ms=0, total_ms=0,
        generated_at=start + timedelta(hours=5), context={}, trigger="manual",
    )
    kiosk = Insight(
        text="kiosk", model="m", eval_ms=0, total_ms=0,
        generated_at=start + timedelta(hours=6), context={}, trigger="kiosk",
    )
    older.id = await save_insight(mock_db, older)
    newer.id = await save_insight(mock_db, newer)
    kiosk.id = await save_insight(mock_db, kiosk)

    r = await client.post(
        "/coach/ack/web-latest",
        headers={"X-API-Key": "test-key"},
        params={"start": start.isoformat(), "end": end.isoformat()},
    )
    assert r.status_code == 200
    assert r.json()["id"] == newer.id

    doc_older = await mock_db["coach_insights"].find_one({"_id": _oid(older.id)})
    doc_kiosk = await mock_db["coach_insights"].find_one({"_id": _oid(kiosk.id)})
    assert doc_older.get("acked_at") is None
    assert doc_kiosk.get("acked_at") is None


@pytest.mark.asyncio
async def test_ack_kiosk_latest_picks_kiosk_only(client, mock_db):
    start, end = resolve_day_window(None, None)
    manual = Insight(
        text="manual", model="m", eval_ms=0, total_ms=0,
        generated_at=start + timedelta(hours=2), context={}, trigger="manual",
    )
    kiosk = Insight(
        text="kiosk", model="m", eval_ms=0, total_ms=0,
        generated_at=start + timedelta(hours=3), context={}, trigger="kiosk",
    )
    manual.id = await save_insight(mock_db, manual)
    kiosk.id = await save_insight(mock_db, kiosk)
    r = await client.post(
        "/coach/ack/kiosk-latest",
        headers={"X-API-Key": "test-key"},
        params={"start": start.isoformat(), "end": end.isoformat()},
    )
    assert r.status_code == 200
    assert r.json()["id"] == kiosk.id


@pytest.mark.asyncio
async def test_ack_latest_returns_null_when_nothing_eligible(client):
    r = await client.post(
        "/coach/ack/web-latest",
        headers={"X-API-Key": "test-key"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {"id": None, "acked_at": None}


@pytest.mark.asyncio
async def test_history_marks_acked_and_filters_by_surface(mock_db):
    start, _end = resolve_day_window(None, None)
    web_acked = Insight(
        text="seen", model="m", eval_ms=0, total_ms=0,
        generated_at=start + timedelta(hours=1), context={}, trigger="manual",
        acked_at=datetime.now(UTC),
    )
    web_fresh = Insight(
        text="new", model="m", eval_ms=0, total_ms=0,
        generated_at=start + timedelta(hours=2), context={}, trigger="manual",
    )
    kiosk_only = Insight(
        text="k", model="m", eval_ms=0, total_ms=0,
        generated_at=start + timedelta(hours=3), context={}, trigger="kiosk",
    )
    for i in (web_acked, web_fresh, kiosk_only):
        i.id = await save_insight(mock_db, i)

    rows = await recent_insights(mock_db, since=start, surface="manual")
    texts = {r["text"]: r for r in rows}
    assert "k" not in texts
    assert texts["seen"]["acked"] is True
    assert texts["new"]["acked"] is False

    krows = await recent_insights(mock_db, since=start, surface="kiosk")
    assert len(krows) == 1
    assert krows[0]["text"] == "k"


@pytest.mark.asyncio
async def test_ack_kiosk_latest_clears_kiosk_cache(client, mock_db):
    # Reach the app via the client's ASGI transport to seed the cache.
    app = client._transport.app  # type: ignore[attr-defined]
    app.state.kiosk_cache = {"|": {"stored_at": datetime.now(UTC), "payload": {}}}
    start, _end = resolve_day_window(None, None)
    kiosk = Insight(
        text="k", model="m", eval_ms=0, total_ms=0,
        generated_at=start + timedelta(hours=1), context={}, trigger="kiosk",
    )
    kiosk.id = await save_insight(mock_db, kiosk)
    r = await client.post(
        "/coach/ack/kiosk-latest",
        headers={"X-API-Key": "test-key"},
    )
    assert r.status_code == 200
    assert app.state.kiosk_cache == {}


def test_render_brief_prompt_flags_acked_messages():
    from app.services.coach.brief import render_brief_prompt  # noqa: PLC0415
    from app.services.coach.context import Findings  # noqa: PLC0415
    history = [
        {"trigger": "manual", "text": "old nudge", "acked": True,
         "generated_at": datetime.now(UTC)},
        {"trigger": "manual", "text": "fresh nudge", "acked": False,
         "generated_at": datetime.now(UTC)},
    ]
    findings = Findings()
    prompt = render_brief_prompt(findings, history)
    assert "[acked]" in prompt or "acknowledged" in prompt
    assert "old nudge" in prompt
    assert "fresh nudge" in prompt
