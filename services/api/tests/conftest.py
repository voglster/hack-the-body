import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from app.config import Settings
from app.db import ensure_collections
from app.main import create_app
from app.services.coach.habits import ensure_default_habits


def llm_body(text: str = "", tool_calls: list | None = None) -> dict:
    """An OpenAI-compatible chat-completion body, as the LiteLLM proxy returns it.

    Tests patch `httpx.AsyncClient.post` and hand the result to
    `app.services.llm.complete`, so the mock has to match the proxy's
    wire shape rather than Ollama's native `{"response": ...}`.
    """
    message: dict = {"role": "assistant", "content": text}
    if tool_calls is not None:
        message["tool_calls"] = tool_calls
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "ollama/qwen3.6:35b-a3b-q8_0-fast",
        "choices": [{"index": 0, "finish_reason": "stop", "message": message}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20},
    }


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
