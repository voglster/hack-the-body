import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.config import Settings
from app.db import ensure_collections
from app.main import create_app
from app.services.coach.habits import ensure_default_habits


@pytest.fixture
async def mock_db():
    client = AsyncMongoMockClient()
    db = client["testdb"]
    await ensure_collections(db)
    # Mirror production startup so tests see the same seeded habits the
    # FE and HA automations rely on (e.g. the canonical Vitamins habit
    # with on_done_action="log_vitamins").
    await ensure_default_habits(db)
    yield db


@pytest.fixture
def settings():
    return Settings(mongo_url="mongodb://fake", mongo_db="testdb", api_key="test-key")


@pytest.fixture
async def client(settings, mock_db):
    app = create_app(settings)
    app.state.db = mock_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
