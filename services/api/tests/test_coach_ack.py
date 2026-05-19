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
async def test_ack_latest_returns_null_when_nothing_eligible(client, mock_db):
    r = await client.post(
        "/coach/ack/web-latest",
        headers={"X-API-Key": "test-key"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {"id": None, "acked_at": None}
