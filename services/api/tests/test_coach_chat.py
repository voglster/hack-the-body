"""Coach chat agent loop — driven by a stateful mock Ollama."""
from unittest.mock import patch

import httpx

from app.services.coach.chat import MAX_ITERATIONS, reply
from app.services.coach.threads import Turn, create_thread


def _stateful_ollama(responses: list[dict]):
    """Return an async POST that yields one queued response per call."""
    seq = list(responses)
    async def _post(_self, _url, json=None):
        del json
        body = seq.pop(0)
        class _R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return body
        return _R()
    return _post


class _FakeSettings:
    ollama_url = "http://x"
    ollama_model = "test-model"
    coach_timeout_s = 5


async def test_reply_handles_tool_call_then_final_text(mock_db):
    # Seed a thread (brief turn 1) so we have somewhere to append.
    tid = await create_thread(
        mock_db, initial_turn=Turn(role="coach", text="hi"),
    )

    # Ollama returns tool_call first, then final content after seeing tool result.
    sequence = [
        {  # Iteration 1: model wants to call `trend`
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [{
                    "function": {
                        "name": "trend",
                        "arguments": {"metric": "hrv", "window_days": 7},
                    },
                }],
            },
        },
        {  # Iteration 2: model produces final text
            "message": {
                "role": "assistant",
                "content": "Your HRV is steady at 50ms — nothing to address.",
                "tool_calls": [],
            },
        },
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
    looping = {
        "message": {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "function": {
                    "name": "trend",
                    "arguments": {"metric": "hrv", "window_days": 7},
                },
            }],
        },
    }
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
    sequence = [{
        "message": {"role": "assistant", "content": "ok", "tool_calls": []},
    }]
    with patch.object(httpx.AsyncClient, "post", _stateful_ollama(sequence)):
        await reply(_FakeSettings(), mock_db, tid, user_message="hello")
    doc = await mock_db["coach_threads"].find_one()
    assert doc["turns"][1]["role"] == "user"
    assert doc["turns"][1]["text"] == "hello"
    assert doc["turns"][2]["role"] == "coach"
