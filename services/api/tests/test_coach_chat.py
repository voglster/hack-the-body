"""Coach chat agent loop — driven by a stateful mock Ollama."""
from unittest.mock import patch

import httpx

from app.services.coach.chat import MAX_ITERATIONS, reply
from app.services.coach.threads import Turn, create_thread
from tests.conftest import llm_body


def _stateful_ollama(responses: list[dict]):
    """Return an async POST that yields one queued response per call."""
    seq = list(responses)
    async def _post(_self, _url, json=None, **_kw):
        del json
        body = seq.pop(0)
        class _R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return body
        return _R()
    return _post


class _FakeSettings:
    llm_base_url = "http://x/v1"
    llm_api_key = "test"
    llm_model = "test-model"
    coach_timeout_s = 5


async def test_reply_handles_tool_call_then_final_text(mock_db):
    # Seed a thread (brief turn 1) so we have somewhere to append.
    tid = await create_thread(
        mock_db, initial_turn=Turn(role="coach", text="hi"),
    )

    # Ollama returns tool_call first, then final content after seeing tool result.
    sequence = [
        # Iteration 1: model wants to call `trend`
        llm_body("", tool_calls=[{
            "id": "call_1", "type": "function",
            "function": {
                "name": "trend",
                "arguments": {"metric": "hrv", "window_days": 7},
            },
        }]),
        # Iteration 2: model produces final text
        llm_body("Your HRV is steady at 50ms — nothing to address.", tool_calls=[]),
    ]
    with patch.object(httpx.AsyncClient, "post", _stateful_ollama(sequence)):
        coach_turn = await reply(
            _FakeSettings(), mock_db, tid, user_message="how's my HRV?",
        )

    assert "HRV is steady" in coach_turn["text"]
    assert coach_turn["tool_calls"]
    assert coach_turn["tool_calls"][0]["name"] == "trend"
    # Thread now has: brief, user, coach. Three turns.
    doc = await mock_db["coach_threads"].find_one()
    assert len(doc["turns"]) == 3
    assert doc["turns"][1]["role"] == "user"
    assert doc["turns"][2]["role"] == "coach"


async def test_reply_hits_iteration_cap_and_forces_final_turn(mock_db):
    tid = await create_thread(
        mock_db, initial_turn=Turn(role="coach", text="hi"),
    )
    # Always returns a tool_call → loop will hit MAX_ITERATIONS.
    looping = llm_body("", tool_calls=[{
        "id": "call_loop", "type": "function",
        "function": {
            "name": "trend",
            "arguments": {"metric": "hrv", "window_days": 7},
        },
    }])
    sequence = [looping] * (MAX_ITERATIONS + 2)
    with patch.object(httpx.AsyncClient, "post", _stateful_ollama(sequence)):
        coach_turn = await reply(
            _FakeSettings(), mock_db, tid, user_message="loop please",
        )
    # The driver synthesizes a final reply rather than looping forever.
    assert coach_turn["text"]  # non-empty
    assert "limit" in coach_turn["text"].lower() or "stopped" in coach_turn["text"].lower()


async def test_reply_appends_user_turn_before_coach_turn(mock_db):
    tid = await create_thread(
        mock_db, initial_turn=Turn(role="coach", text="hi"),
    )
    sequence = [llm_body("ok", tool_calls=[])]
    with patch.object(httpx.AsyncClient, "post", _stateful_ollama(sequence)):
        await reply(_FakeSettings(), mock_db, tid, user_message="hello")
    doc = await mock_db["coach_threads"].find_one()
    assert doc["turns"][1]["role"] == "user"
    assert doc["turns"][1]["text"] == "hello"
    assert doc["turns"][2]["role"] == "coach"


async def test_reply_stores_prose_not_the_json_envelope(mock_db):
    """The chat surface shares SYSTEM_PROMPT with the brief, so the model
    answers in a {"text": ..., "anchors": ...} envelope. The user must read
    the prose, never the raw JSON."""
    tid = await create_thread(mock_db, initial_turn=Turn(role="coach", text="hi"))
    envelope = llm_body(
        '{ "text": "You slept 8h 36m with a score of 86.", "anchors": {} }'
    )
    with patch.object(httpx.AsyncClient, "post", _stateful_ollama([envelope])):
        coach_turn = await reply(
            _FakeSettings(), mock_db, tid, user_message="how did I sleep?",
        )
    assert coach_turn["text"] == "You slept 8h 36m with a score of 86."


async def test_reply_carries_anchors_through_to_the_turn(mock_db):
    tid = await create_thread(mock_db, initial_turn=Turn(role="coach", text="hi"))
    envelope = llm_body(
        '{"text": "Lights out at {{lights_out}}.", '
        '"anchors": {"lights_out": "2026-05-19T22:00:00-05:00"}}'
    )
    with patch.object(httpx.AsyncClient, "post", _stateful_ollama([envelope])):
        coach_turn = await reply(
            _FakeSettings(), mock_db, tid, user_message="when is bedtime?",
        )
    assert coach_turn["text"] == "Lights out at {{lights_out}}."
    assert coach_turn["anchors"] == {"lights_out": "2026-05-19T22:00:00-05:00"}


async def test_reply_keeps_bare_prose_when_model_ignores_the_envelope(mock_db):
    tid = await create_thread(mock_db, initial_turn=Turn(role="coach", text="hi"))
    with patch.object(
        httpx.AsyncClient, "post", _stateful_ollama([llm_body("Just plain prose.")]),
    ):
        coach_turn = await reply(
            _FakeSettings(), mock_db, tid, user_message="hi",
        )
    assert coach_turn["text"] == "Just plain prose."
    assert "anchors" not in coach_turn
