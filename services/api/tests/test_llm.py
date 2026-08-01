"""Tests for the LiteLLM proxy client and its single-flight guard."""
import asyncio
from unittest.mock import patch

import httpx
import pytest

from app.services.llm import LLMError, complete, single_flight
from tests.conftest import llm_body


class _Settings:
    llm_base_url = "http://proxy/v1"
    llm_api_key = "sk-test"
    llm_model = "test-model"
    coach_timeout_s = 5.0


def _post_returning(body, status: int = 200, capture: dict | None = None):
    class _R:
        status_code = status
        def raise_for_status(self):
            if status >= 400:
                raise httpx.HTTPStatusError(
                    "boom", request=httpx.Request("POST", "http://proxy/v1"),
                    response=httpx.Response(status, text="upstream exploded"),
                )
        def json(self): return body

    async def _post(_self, _url, json=None, headers=None, **_kw):
        if capture is not None:
            capture["json"] = json
            capture["headers"] = headers
            capture["url"] = _url
        return _R()
    return _post


async def test_complete_returns_text_and_model():
    with patch.object(httpx.AsyncClient, "post", _post_returning(llm_body("hello"))):
        out = await complete(_Settings(), messages=[{"role": "user", "content": "hi"}])
    assert out.text == "hello"
    assert out.model == "ollama/qwen3.6:35b-a3b-q8_0-fast"
    assert out.usage["total_tokens"] == 20


async def test_complete_sends_bearer_key_and_configured_model():
    cap: dict = {}
    with patch.object(httpx.AsyncClient, "post", _post_returning(llm_body("x"), capture=cap)):
        await complete(_Settings(), messages=[{"role": "user", "content": "hi"}])
    assert cap["headers"]["Authorization"] == "Bearer sk-test"
    assert cap["json"]["model"] == "test-model"
    assert cap["url"] == "http://proxy/v1/chat/completions"


async def test_json_mode_sets_response_format():
    cap: dict = {}
    with patch.object(httpx.AsyncClient, "post", _post_returning(llm_body("{}"), capture=cap)):
        await complete(
            _Settings(), messages=[{"role": "user", "content": "hi"}], json_mode=True,
        )
    assert cap["json"]["response_format"] == {"type": "json_object"}


async def test_explicit_model_overrides_default():
    cap: dict = {}
    with patch.object(httpx.AsyncClient, "post", _post_returning(llm_body("x"), capture=cap)):
        await complete(
            _Settings(), messages=[{"role": "user", "content": "hi"}], model="other-model",
        )
    assert cap["json"]["model"] == "other-model"


async def test_tool_calls_are_surfaced():
    calls = [{"id": "c1", "type": "function",
              "function": {"name": "trend", "arguments": "{}"}}]
    with patch.object(httpx.AsyncClient, "post", _post_returning(llm_body("", tool_calls=calls))):
        out = await complete(_Settings(), messages=[{"role": "user", "content": "hi"}])
    assert out.tool_calls[0]["function"]["name"] == "trend"


async def test_upstream_http_error_becomes_llm_error():
    with (
        patch.object(httpx.AsyncClient, "post", _post_returning(None, status=502)),
        pytest.raises(LLMError, match="502"),
    ):
        await complete(_Settings(), messages=[{"role": "user", "content": "hi"}])


async def test_malformed_body_becomes_llm_error():
    with (
        patch.object(httpx.AsyncClient, "post", _post_returning({"nope": 1})),
        pytest.raises(LLMError, match="unexpected response shape"),
    ):
        await complete(_Settings(), messages=[{"role": "user", "content": "hi"}])


# ---- single_flight ------------------------------------------------------
#
# This is the guard against the GPU pile-up: the kiosk polls on a timer, and
# before it existed each poll started its own generation that kept running
# after its caller had already timed out.


async def test_concurrent_callers_share_one_generation():
    started = [0]
    release = asyncio.Event()

    async def _slow():
        started[0] += 1
        await release.wait()
        return "result"

    waiters = [asyncio.create_task(single_flight("k", _slow)) for _ in range(5)]
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.gather(*waiters) == ["result"] * 5
    assert started[0] == 1


async def test_sequential_calls_do_not_share_a_finished_result():
    started = [0]

    async def _quick():
        started[0] += 1
        return started[0]

    assert await single_flight("k2", _quick) == 1
    assert await single_flight("k2", _quick) == 2


async def test_one_caller_giving_up_does_not_kill_the_others():
    release = asyncio.Event()

    async def _slow():
        await release.wait()
        return "survived"

    stayer = asyncio.create_task(single_flight("k3", _slow))
    quitter = asyncio.create_task(single_flight("k3", _slow))
    await asyncio.sleep(0)

    quitter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await quitter

    release.set()
    assert await stayer == "survived"


async def test_last_caller_leaving_cancels_the_generation():
    """The whole point: nothing keeps burning GPU once everyone has gone."""
    cancelled = asyncio.Event()

    async def _slow():
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    only = asyncio.create_task(single_flight("k4", _slow))
    await asyncio.sleep(0)
    only.cancel()
    with pytest.raises(asyncio.CancelledError):
        await only

    await asyncio.wait_for(cancelled.wait(), timeout=1)


async def test_failure_propagates_to_every_waiter():
    async def _boom():
        raise LLMError("upstream down")

    waiters = [asyncio.create_task(single_flight("k5", _boom)) for _ in range(3)]
    results = await asyncio.gather(*waiters, return_exceptions=True)
    assert all(isinstance(r, LLMError) for r in results)


async def test_distinct_keys_do_not_share():
    async def _make(tag):
        async def _f():
            return tag
        return _f

    a = await single_flight("day-a", await _make("a"))
    b = await single_flight("day-b", await _make("b"))
    assert (a, b) == ("a", "b")
