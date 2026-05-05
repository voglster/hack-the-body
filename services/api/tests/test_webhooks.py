import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.config import Settings
from app.main import create_app


@pytest.fixture
async def app_client():
    settings = Settings(
        api_key="test-key",
        mongo_url="mongodb://stub",
        mongo_db="htb_test",
        hevy_webhook_secret="webhook-secret",  # noqa: S106
    )
    app = create_app(settings=settings)
    # Replace the real Mongo client created by the lifespan with a mock.
    mock_client = AsyncMongoMockClient()
    app.state.mongo_client = mock_client
    app.state.db = mock_client["htb_test"]
    from app.db import ensure_collections
    await ensure_collections(app.state.db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, app


@pytest.mark.asyncio
async def test_webhook_rejects_missing_auth(app_client):
    ac, _ = app_client
    r = await ac.post("/webhooks/hevy", json={"event": "workout.created", "id": "abc"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_webhook_rejects_wrong_secret(app_client):
    ac, _ = app_client
    r = await ac.post(
        "/webhooks/hevy",
        json={"event": "workout.created", "id": "abc"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_webhook_accepts_valid_request_and_writes_log(app_client):
    ac, app = app_client
    r = await ac.post(
        "/webhooks/hevy",
        json={"event": "workout.updated", "id": "wkid-1"},
        headers={"Authorization": "Bearer webhook-secret"},
    )
    assert r.status_code == 204
    # ingestion_log row queued for the ingestor
    rows = [d async for d in app.state.db["ingestion_log"].find({"source": "hevy"})]
    assert len(rows) == 1
    assert rows[0]["status"] == "requested"
    assert rows[0]["payload"]["workout_id"] == "wkid-1"
    assert rows[0]["payload"]["event"] == "workout.updated"


@pytest.mark.asyncio
async def test_webhook_rejects_malformed_body(app_client):
    ac, _ = app_client
    r = await ac.post(
        "/webhooks/hevy",
        json={"random": "garbage"},
        headers={"Authorization": "Bearer webhook-secret"},
    )
    assert r.status_code == 422  # FastAPI validation error
