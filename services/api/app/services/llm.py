"""OpenAI-compatible LLM client, pointed at the LiteLLM proxy.

Every model call in the app goes through `complete()`. Two things this
centralises that the old direct-to-Ollama calls got wrong:

**Thinking is off by default.** Ollama 0.32 flipped reasoning on unless a
request opts out, which turned a 2-second coach brief into a 45-second one
and tripped `coach_timeout_s`. The proxy's `-fast` model aliases pin
thinking off server-side, so the choice lives in config rather than in
each payload.

**An abandoned request stops costing GPU.** `single_flight()` collapses
concurrent identical calls onto one upstream generation. The kiosk polls
on a timer; before this, every poll that timed out left its generation
running and the next poll started another, stacking until the card was
full.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Any failure talking to the proxy — transport, HTTP, or malformed body."""


class Completion:
    """One model response, normalised across the shapes callers need."""

    def __init__(
        self, *, text: str, tool_calls: list[dict[str, Any]],
        model: str, elapsed_ms: int, usage: dict[str, Any],
    ) -> None:
        self.text = text
        self.tool_calls = tool_calls
        self.model = model
        self.elapsed_ms = elapsed_ms
        self.usage = usage


async def complete(
    settings: Any,
    *,
    messages: list[dict[str, Any]],
    model: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    json_mode: bool = False,
    temperature: float = 0.4,
    max_tokens: int | None = None,
    timeout_s: float | None = None,
) -> Completion:
    model = model or settings.llm_model
    timeout_s = timeout_s if timeout_s is not None else settings.coach_timeout_s

    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    if tools:
        payload["tools"] = tools
    if json_mode:
        payload["response_format"] = {"type": "json_object"}

    headers = {"Authorization": f"Bearer {settings.llm_api_key}"}
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout_s) as c:
            r = await c.post(
                f"{settings.llm_base_url}/chat/completions",
                json=payload, headers=headers,
            )
            r.raise_for_status()
            data = r.json()
    except httpx.HTTPStatusError as e:
        raise LLMError(
            f"{model}: HTTP {e.response.status_code}: {e.response.text[:300]}"
        ) from e
    except httpx.HTTPError as e:
        raise LLMError(f"{model}: {type(e).__name__}: {e}") from e

    elapsed_ms = int((time.monotonic() - started) * 1000)
    try:
        choice = data["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"{model}: unexpected response shape: {str(data)[:300]}") from e

    text = (message.get("content") or "").strip()
    tool_calls = message.get("tool_calls") or []
    if not text and not tool_calls and choice.get("finish_reason") == "length":
        # A thinking model draws reasoning tokens from the same budget as the
        # answer, so too small a max_tokens yields a 200 with empty content.
        # Failing loudly beats persisting a blank insight.
        raise LLMError(
            f"{model}: hit the {max_tokens}-token budget before emitting an "
            "answer — raise max_tokens or use a non-thinking model alias"
        )

    return Completion(
        text=text,
        tool_calls=tool_calls,
        model=data.get("model") or model,
        elapsed_ms=elapsed_ms,
        usage=data.get("usage") or {},
    )


_inflight: dict[str, tuple[asyncio.Task[Any], list[int]]] = {}


async def single_flight(key: str, factory: Any) -> Any:
    """Run `factory()` under `key`, or join the call already running under it.

    Callers that arrive mid-generation await the same result rather than
    starting a second one. A caller giving up (timeout, client disconnect)
    drops its own await; the shared task is cancelled only when the *last*
    waiter leaves, so one slow poller doesn't kill a generation the others
    are still waiting on — and nothing keeps running once they've all gone,
    which is what actually frees the GPU.
    """
    entry = _inflight.get(key)
    if entry is None or entry[0].done():
        entry = (asyncio.create_task(factory()), [0])
        _inflight[key] = entry
    task, waiters = entry
    waiters[0] += 1

    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        if waiters[0] <= 1 and not task.done():
            task.cancel()
        raise
    finally:
        waiters[0] -= 1
        if _inflight.get(key) is entry and (task.done() or waiters[0] <= 0):
            _inflight.pop(key, None)
