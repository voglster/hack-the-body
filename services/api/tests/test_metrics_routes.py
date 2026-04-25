from datetime import UTC, datetime

from app.models.metrics import Weight
from app.services.metrics_repo import MetricsRepo


async def test_get_latest_weight_requires_auth(client):
    r = await client.get("/metrics/weight/latest")
    assert r.status_code == 401


async def test_get_latest_weight_returns_value(client, mock_db):
    repo = MetricsRepo(mock_db)
    await repo.insert_weight(
        Weight(ts=datetime.now(UTC), kg=108.9,
               source="garmin", source_id="w1")
    )
    r = await client.get("/metrics/weight/latest", headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    assert r.json()["kg"] == 108.9


async def test_summary_returns_all_latest(client, mock_db):
    repo = MetricsRepo(mock_db)
    await repo.insert_weight(
        Weight(ts=datetime.now(UTC), kg=108.9,
               source="garmin", source_id="w1")
    )
    r = await client.get("/metrics/summary", headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    body = r.json()
    assert "weight" in body
    assert body["weight"]["kg"] == 108.9
