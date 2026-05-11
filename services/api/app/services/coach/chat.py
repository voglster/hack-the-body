"""Coach chat agent loop — wraps Ollama /api/chat with bounded tool use.

Public entry point is `reply()`: takes a thread_id and a user message,
runs an iteration-capped tool loop against Ollama, appends both the user
turn and the coach turn to the thread, and returns the coach turn dict.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from pymongo.asynchronous.database import AsyncDatabase

from app.services.coach.brief import SYSTEM_PROMPT, USER_PROFILE
from app.services.coach.context import build_findings
from app.services.coach.threads import Turn, append_turn, get_thread
from app.services.coach.tools import dispatch, schema_for_llm
from app.services.food_repo import FoodRepo
from app.services.metrics_repo import MetricsRepo

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 6


async def _build_messages(
    db: AsyncDatabase, thread: dict[str, Any], user_message: str,
) -> list[dict[str, Any]]:
    """Compose the messages array for Ollama /api/chat.

    Front of the array carries the system prompt + a deterministic findings
    snapshot so the model has structured grounding even before any tool call.
    Then each prior turn (coach/user) in order. Then the new user message.
    """
    repo = MetricsRepo(db)
    food_repo = FoodRepo(db)
    findings = await build_findings(repo, food_repo, targets=None)
    system_content = (
        SYSTEM_PROMPT
        + f"\n\nClient: {USER_PROFILE}\n\nFindings (pre-digested):\n"
        + json.dumps(findings.to_dict(), default=str, indent=2)
    )
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_content}]
    for t in thread.get("turns", []):
        role = "assistant" if t["role"] == "coach" else "user"
        messages.append({"role": role, "content": t["text"]})
    messages.append({"role": "user", "content": user_message})
    return messages


async def reply(
    settings: Any, db: AsyncDatabase, thread_id: str, *, user_message: str,
) -> dict[str, Any]:
    """Run one user→coach turn through the agent loop. Returns the coach turn dict."""
    thread = await get_thread(db, thread_id)
    if thread is None:
        raise ValueError(f"thread not found: {thread_id}")

    # Append the user turn first so the loop's iteration record is honest
    # about what the model is responding to.
    await append_turn(db, thread_id, Turn(role="user", text=user_message))

    messages = await _build_messages(db, thread, user_message)
    tool_calls_record: list[dict[str, Any]] = []
    final_text = ""

    async with httpx.AsyncClient(timeout=settings.coach_timeout_s) as client:
        for _ in range(MAX_ITERATIONS):
            payload = {
                "model": settings.ollama_model,
                "messages": messages,
                "tools": schema_for_llm(),
                "stream": False,
            }
            r = await client.post(f"{settings.ollama_url}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
            msg = data.get("message") or {}
            calls = msg.get("tool_calls") or []
            if not calls:
                final_text = (msg.get("content") or "").strip()
                break
            # Append the assistant's tool-call message so the model sees
            # context next iteration.
            messages.append({
                "role": "assistant", "content": msg.get("content") or "",
                "tool_calls": calls,
            })
            for call in calls:
                fn = call.get("function") or {}
                name = fn.get("name") or ""
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                result = await dispatch(db, name, args)
                tool_calls_record.append({
                    "name": name, "args": args, "result": result,
                })
                messages.append({
                    "role": "tool", "name": name,
                    "content": json.dumps(result, default=str),
                })
        else:
            # Loop exhausted without a final content message.
            final_text = (
                "Hit the tool-call limit before reaching a conclusion. "
                "Try a more focused question."
            )

    coach_turn = Turn(
        role="coach", text=final_text or "(empty response)",
        tool_calls=tool_calls_record or None,
        ts=datetime.now(UTC),
    )
    await append_turn(db, thread_id, coach_turn)
    return coach_turn.to_dict()
