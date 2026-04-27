"""Endpoint tests for /nudges."""
from __future__ import annotations

import pytest

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture(autouse=True)
def fix_tz(monkeypatch):
    monkeypatch.setenv("TZ", "America/Denver")


class TestGetNudges:
    async def test_requires_api_key(self, client):
        r = await client.get("/nudges")
        assert r.status_code in (401, 403)

    async def test_empty_db_returns_some_nudges(self, client):
        # Empty DB at default 'now' will likely return at least one nudge
        # depending on time — just assert shape.
        r = await client.get("/nudges", headers=HEADERS)
        assert r.status_code == 200
        body = r.json()
        assert "nudges" in body
        assert "generated_at" in body
        assert isinstance(body["nudges"], list)


class TestDismiss:
    async def test_records_dismissal(self, client, mock_db):
        r = await client.post(
            "/nudges/dismiss",
            headers=HEADERS,
            json={"nudge_id": "vitamins_missing", "until": "end_of_day"},
        )
        assert r.status_code == 200
        # Doc was written
        doc = await mock_db["nudge_dismissals"].find_one({})
        assert doc is not None
        assert "vitamins_missing" in (doc.get("entries") or {})

    async def test_unknown_nudge_id_is_noop_200(self, client):
        r = await client.post(
            "/nudges/dismiss",
            headers=HEADERS,
            json={"nudge_id": "made_up", "until": "end_of_day"},
        )
        assert r.status_code == 200

    async def test_malformed_until_is_422(self, client):
        r = await client.post(
            "/nudges/dismiss",
            headers=HEADERS,
            json={"nudge_id": "x"},  # missing 'until'
        )
        assert r.status_code == 422

    async def test_dismissed_nudge_filtered_from_get(self, client):
        # Dismiss vitamins.
        await client.post(
            "/nudges/dismiss",
            headers=HEADERS,
            json={"nudge_id": "vitamins_missing", "until": "end_of_day"},
        )
        r = await client.get("/nudges", headers=HEADERS)
        ids = [n["id"] for n in r.json()["nudges"]]
        assert "vitamins_missing" not in ids
