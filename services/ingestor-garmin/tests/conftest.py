import json
from pathlib import Path

import pytest
from mongomock_motor import AsyncMongoMockClient


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
async def mock_db():
    client = AsyncMongoMockClient()
    yield client["testdb"]


@pytest.fixture
def fixture():
    def _load(name: str):
        with open(FIXTURES / name) as f:
            return json.load(f)
    return _load
