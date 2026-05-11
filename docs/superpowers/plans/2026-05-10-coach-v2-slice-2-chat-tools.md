# Coach v2 — Slice 2: Threads + Chat + Tool Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the brief into the first turn of a conversation thread the user can reply to, with an LLM agent loop that can call tools (`trend`, `compare_windows`, `food_history`, plus a `recall` stub for Slice 4).

**Architecture:** Brief generation now creates a `coach_threads` doc with turn 1 = the brief, *plus* the existing `coach_insights` row (linked by `thread_id`). A new chat path loads the active thread, runs an Ollama `/api/chat` tool-using loop bounded at 6 iterations, and appends a coach turn. The web dashboard's CoachCard gains a chat panel below the brief.

**Tech Stack:** Python 3.12, FastAPI, Motor (async PyMongo), pytest-asyncio. React 19, TanStack Query, Tailwind. Ollama HTTP API (`/api/chat` for tool-call support; brief path keeps `/api/generate`).

**Spec:** `docs/superpowers/specs/2026-05-10-coach-v2-design.md` (Rollout → Slice 2).

**Slice 1 was:** `docs/superpowers/plans/2026-05-10-coach-v2-slice-1-findings.md` (merged at `839a01d`).

---

## File Structure

**Created (backend)**
- `services/api/app/services/coach/threads.py` — thread repo: `create_thread`, `append_turn`, `get_thread`, `get_active_thread`. Threads are short-lived Mongo docs with inline turns.
- `services/api/app/services/coach/tools.py` — tool registry + 4 tool implementations + JSON-schema definitions for the LLM.
- `services/api/app/services/coach/chat.py` — agent driver: takes a thread + user message, runs the Ollama `/api/chat` tool loop, appends a coach turn. Iteration cap and tool-error wrapping live here.
- `services/api/tests/test_threads.py` — thread repo unit tests.
- `services/api/tests/test_coach_tools.py` — tool registry + per-tool unit tests.
- `services/api/tests/test_coach_chat.py` — agent loop integration tests with a stateful mock Ollama.

**Modified (backend)**
- `services/api/app/services/coach/brief.py` — `generate_insight` now also calls `create_thread` and writes turn 1 alongside the `coach_insights` row. Adds `thread_id` to `Insight` dataclass.
- `services/api/app/services/coach/__init__.py` — re-export the new public surface (`Thread`, `Turn` types; `get_active_thread`; chat driver).
- `services/api/app/routers/coach.py` — add `GET /coach/thread/active`, `POST /coach/thread/{id}/reply`.
- `services/api/tests/test_coach.py` — assert brief now also creates a thread row and surfaces `thread_id`.

**Created (frontend)**
- `services/web/src/components/CoachChatPanel.tsx` — chat panel: turn list + input + submit. Loads via `coachThreadActive`, posts via `coachThreadReply`.
- `services/web/src/components/CoachChatPanel.test.tsx` — minimal render + submit test.

**Modified (frontend)**
- `services/web/src/api/types.ts` — add `CoachTurn`, `CoachThread`, `CoachReplyRequest` types.
- `services/web/src/api/client.ts` — add `coachThreadActive`, `coachThreadReply`.
- `services/web/src/components/CoachCard.tsx` — render `<CoachChatPanel/>` inside the expanded view, below the existing brief block.

**Untouched (by design)**
- `coach_insights`, `coach_feedback` collections — backward-compatible. Feedback still attaches to `insight_id` (turn 1). Mid-thread-turn feedback is **out of scope** for this slice; revisit if needed.
- Memory collections (Slice 4).
- Habits (Slice 3).
- Implicit extraction (Slice 5).
- Scheduler (no change — it already calls `generate_insight`, which now also creates a thread).

---

## Conventions for this plan

- Run backend tests from `services/api/`:
  ```
  cd services/api && .venv/bin/pytest -q
  ```
- Run FE tests from `services/web/`:
  ```
  cd services/web && npm test -- --run
  ```
- Run lint:
  ```
  cd services/api && .venv/bin/ruff check app tests
  ```
- Slice-1 ended at HEAD `839a01d` with 209 tests + 1 baseline lint error.
- Commit after every green task. Conventional Commits.
- DO NOT push until Task 15 (final verification).

---

### Task 1: Thread repo (create + get + append_turn)

**Files:**
- Create: `services/api/app/services/coach/threads.py`
- Create: `services/api/tests/test_threads.py`

- [ ] **Step 1: Write the failing tests**

Create `services/api/tests/test_threads.py`:

```python
"""Coach thread repo — short-lived conversation docs with inline turns."""
from datetime import UTC, datetime, timedelta

import pytest

from app.services.coach.threads import (
    Turn,
    append_turn,
    create_thread,
    get_active_thread,
    get_thread,
)


async def test_create_thread_writes_initial_coach_turn(mock_db):
    tid = await create_thread(
        mock_db,
        initial_turn=Turn(role="coach", text="Sleep solid. On track."),
    )
    assert tid
    doc = await mock_db["coach_threads"].find_one({"_id": __import__("bson").ObjectId(tid)})
    assert doc is not None
    assert doc["turns"][0]["role"] == "coach"
    assert doc["turns"][0]["text"] == "Sleep solid. On track."
    assert doc["surface"] == "web"
    assert doc["started_at"] is not None
    assert doc["last_activity_at"] is not None
    assert doc.get("closed_at") is None


async def test_append_turn_extends_existing_thread(mock_db):
    tid = await create_thread(
        mock_db, initial_turn=Turn(role="coach", text="hi"),
    )
    await append_turn(
        mock_db, tid, Turn(role="user", text="why is my HRV low?"),
    )
    doc = await get_thread(mock_db, tid)
    assert len(doc["turns"]) == 2
    assert doc["turns"][1]["role"] == "user"
    assert doc["turns"][1]["text"] == "why is my HRV low?"


async def test_get_active_thread_returns_most_recent_open(mock_db):
    """The active thread is the newest non-closed thread."""
    older = await create_thread(mock_db, initial_turn=Turn(role="coach", text="old"))
    newer = await create_thread(mock_db, initial_turn=Turn(role="coach", text="new"))
    active = await get_active_thread(mock_db)
    assert active is not None
    assert str(active["_id"]) == newer


async def test_get_active_thread_returns_none_when_no_threads(mock_db):
    assert await get_active_thread(mock_db) is None


async def test_append_turn_updates_last_activity(mock_db):
    tid = await create_thread(mock_db, initial_turn=Turn(role="coach", text="hi"))
    before = (await get_thread(mock_db, tid))["last_activity_at"]
    # Force a small clock advance
    await append_turn(mock_db, tid, Turn(role="user", text="hey"))
    after = (await get_thread(mock_db, tid))["last_activity_at"]
    assert after >= before
```

- [ ] **Step 2: Run the tests to verify they fail**

```
cd services/api && .venv/bin/pytest tests/test_threads.py -v
```

Expected: FAIL with `ImportError` on `app.services.coach.threads`.

- [ ] **Step 3: Implement the thread repo**

Create `services/api/app/services/coach/threads.py`:

```python
"""Coach conversation threads — short-lived Mongo docs with inline turns.

Each brief generates a new thread (turn 1 = the brief). User replies and
coach responses append turns inline. Threads close on idle >2h (handled
elsewhere); for now they're effectively per-day.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId
from pymongo.asynchronous.database import AsyncDatabase


@dataclass
class Turn:
    role: str  # "coach" | "user"
    text: str
    tool_calls: list[dict[str, Any]] | None = None
    findings_snapshot: dict[str, Any] | None = None
    ts: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"role": self.role, "text": self.text, "ts": self.ts}
        if self.tool_calls is not None:
            out["tool_calls"] = self.tool_calls
        if self.findings_snapshot is not None:
            out["findings_snapshot"] = self.findings_snapshot
        return out


async def create_thread(
    db: AsyncDatabase, *, initial_turn: Turn, surface: str = "web",
) -> str:
    now = datetime.now(UTC)
    doc = {
        "started_at": now,
        "last_activity_at": now,
        "closed_at": None,
        "surface": surface,
        "turns": [initial_turn.to_dict()],
    }
    res = await db["coach_threads"].insert_one(doc)
    return str(res.inserted_id)


async def append_turn(db: AsyncDatabase, thread_id: str, turn: Turn) -> None:
    await db["coach_threads"].update_one(
        {"_id": ObjectId(thread_id)},
        {
            "$push": {"turns": turn.to_dict()},
            "$set": {"last_activity_at": datetime.now(UTC)},
        },
    )


async def get_thread(db: AsyncDatabase, thread_id: str) -> dict[str, Any] | None:
    return await db["coach_threads"].find_one({"_id": ObjectId(thread_id)})


async def get_active_thread(db: AsyncDatabase) -> dict[str, Any] | None:
    """Return the most recent non-closed thread, or None if none exists."""
    return await db["coach_threads"].find_one(
        {"closed_at": None},
        sort=[("started_at", -1)],
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd services/api && .venv/bin/pytest tests/test_threads.py -v
```

Expected: 5 PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/coach/threads.py services/api/tests/test_threads.py
git commit -m "feat(coach): add thread repo (create/append_turn/get/get_active)"
```

---

### Task 2: Brief generates a thread (turn 1 = brief text)

**Files:**
- Modify: `services/api/app/services/coach/brief.py`
- Modify: `services/api/tests/test_coach.py`

`generate_insight` now creates a `coach_threads` doc with turn 1 = the rendered brief and stores `thread_id` on the saved insight. `Insight` gains a `thread_id` field. The `coach_insights` row continues to exist for backward compat + feedback.

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_coach.py`:

```python
async def test_insight_creates_thread_with_brief_as_turn_one(
    client, mock_db, fake_ollama_response,
):
    """Slice 2: every brief opens a new thread, with the brief text as
    turn 1 (role=coach). The insight row carries a thread_id pointing
    to that thread."""
    await _seed(mock_db)

    class _MockResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return fake_ollama_response
    async def _fake_post(_self, _url, json=None):
        del json
        return _MockResp()

    with patch.object(httpx.AsyncClient, "post", _fake_post):
        r = await client.get("/coach/insight", headers=HEADERS)

    body = r.json()
    assert body.get("thread_id"), "insight response should carry thread_id"

    # The thread was created with one coach turn equal to the insight text.
    thread = await mock_db["coach_threads"].find_one(
        {"_id": __import__("bson").ObjectId(body["thread_id"])},
    )
    assert thread is not None
    assert len(thread["turns"]) == 1
    assert thread["turns"][0]["role"] == "coach"
    assert thread["turns"][0]["text"] == body["text"]

    # And the saved insight row has thread_id stored.
    saved = await mock_db["coach_insights"].find_one(
        {"_id": __import__("bson").ObjectId(body["id"])},
    )
    assert saved["thread_id"] == body["thread_id"]
```

- [ ] **Step 2: Run the test to verify it fails**

```
cd services/api && .venv/bin/pytest tests/test_coach.py::test_insight_creates_thread_with_brief_as_turn_one -v
```

Expected: FAIL — `body.get("thread_id")` is None.

- [ ] **Step 3: Add `thread_id` to `Insight` and update `generate_insight`/`save_insight`**

In `services/api/app/services/coach/brief.py`:

Add the new field to the `Insight` dataclass:

```python
@dataclass
class Insight:
    text: str
    model: str
    eval_ms: int
    total_ms: int
    generated_at: datetime
    context: dict[str, Any]
    trigger: str = "manual"
    id: str | None = None
    food_totals: dict[str, Any] | None = None
    history_snapshot: list[dict[str, Any]] | None = None
    prompt: str | None = None
    system_prompt: str | None = None
    thread_id: str | None = None  # populated by generate_insight after thread creation
```

Update `save_insight` to persist `thread_id`:

```python
async def save_insight(db: AsyncDatabase, insight: Insight) -> str:
    doc = {
        "text": insight.text,
        "model": insight.model,
        "eval_ms": insight.eval_ms,
        "total_ms": insight.total_ms,
        "generated_at": insight.generated_at,
        "context": insight.context,
        "trigger": insight.trigger,
        "food_totals": insight.food_totals,
        "history_snapshot": insight.history_snapshot,
        "prompt": insight.prompt,
        "system_prompt": insight.system_prompt,
        "thread_id": insight.thread_id,
    }
    res = await db["coach_insights"].insert_one(doc)
    return str(res.inserted_id)
```

Update the end of `generate_insight` to create a thread before saving:

```python
    # Create a thread with the brief as turn 1 BEFORE saving the insight so
    # the insight row can store thread_id.
    from app.services.coach.threads import Turn, create_thread
    thread_id = await create_thread(
        db,
        initial_turn=Turn(
            role="coach", text=insight.text, findings_snapshot=findings.to_dict(),
        ),
    )
    insight.thread_id = thread_id
    insight.id = await save_insight(db, insight)
    return insight
```

(Replace the existing `insight.id = await save_insight(db, insight)` call with the block above.)

- [ ] **Step 4: Update the router's serializer to surface `thread_id`**

In `services/api/app/routers/coach.py`, update `_serialize`:

```python
def _serialize(insight: Insight) -> dict[str, Any]:
    return {
        "id": insight.id,
        "text": insight.text,
        "model": insight.model,
        "eval_ms": insight.eval_ms,
        "total_ms": insight.total_ms,
        "generated_at": insight.generated_at,
        "context": insight.context,
        "trigger": insight.trigger,
        "food_totals": insight.food_totals,
        "thread_id": insight.thread_id,
    }
```

- [ ] **Step 5: Run the test**

```
cd services/api && .venv/bin/pytest tests/test_coach.py::test_insight_creates_thread_with_brief_as_turn_one -v
```

Expected: PASS.

- [ ] **Step 6: Run the full suite**

```
cd services/api && .venv/bin/pytest -q
```

Expected: 215 PASS (209 baseline + 5 from Task 1 + 1 new here).

- [ ] **Step 7: Commit**

```bash
git add services/api/app/services/coach/brief.py services/api/app/routers/coach.py services/api/tests/test_coach.py
git commit -m "feat(coach): brief now opens a thread with turn 1 = brief text"
```

---

### Task 3: `GET /coach/thread/active` endpoint

**Files:**
- Modify: `services/api/app/routers/coach.py`
- Modify: `services/api/tests/test_coach.py`

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_coach.py`:

```python
async def test_thread_active_returns_most_recent_thread(
    client, mock_db, fake_ollama_response,
):
    """GET /coach/thread/active returns the latest thread with its turns.
    When no thread exists yet, 404."""
    # No thread → 404.
    r = await client.get("/coach/thread/active", headers=HEADERS)
    assert r.status_code == 404

    # Generate one brief to seed a thread.
    await _seed(mock_db)

    class _MockResp:
        status_code = 200
        def raise_for_status(self): pass
        def json(self): return fake_ollama_response
    async def _fake_post(_self, _url, json=None):
        del json
        return _MockResp()

    with patch.object(httpx.AsyncClient, "post", _fake_post):
        await client.get("/coach/insight", headers=HEADERS)

    r = await client.get("/coach/thread/active", headers=HEADERS)
    assert r.status_code == 200
    body = r.json()
    assert "id" in body
    assert isinstance(body["turns"], list)
    assert len(body["turns"]) == 1
    assert body["turns"][0]["role"] == "coach"
```

- [ ] **Step 2: Run it to verify it fails**

```
cd services/api && .venv/bin/pytest tests/test_coach.py::test_thread_active_returns_most_recent_thread -v
```

Expected: FAIL — endpoint returns 404 even after a thread exists (route doesn't exist; FastAPI 404s on unknown path).

- [ ] **Step 3: Implement the endpoint**

In `services/api/app/routers/coach.py`, add after the `recent` route:

```python
@router.get("/thread/active")
async def thread_active(request: Request) -> dict[str, Any]:
    """Return the most recent non-closed coach thread with its turns.
    Used by the FE chat panel to render the conversation under today's brief.
    """
    from app.services.coach.threads import get_active_thread
    db = request.app.state.db
    doc = await get_active_thread(db)
    if doc is None:
        raise HTTPException(status_code=404, detail="no active thread")
    return {
        "id": str(doc["_id"]),
        "started_at": doc["started_at"],
        "last_activity_at": doc["last_activity_at"],
        "surface": doc.get("surface", "web"),
        "turns": doc["turns"],
    }
```

- [ ] **Step 4: Run the test**

```
cd services/api && .venv/bin/pytest tests/test_coach.py::test_thread_active_returns_most_recent_thread -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/routers/coach.py services/api/tests/test_coach.py
git commit -m "feat(coach): add GET /coach/thread/active endpoint"
```

---

### Task 4: Tool registry skeleton

**Files:**
- Create: `services/api/app/services/coach/tools.py`
- Create: `services/api/tests/test_coach_tools.py`

The registry holds an ordered list of tools, exposes their JSON schemas for the LLM, and dispatches by name. Each tool is an async function `(db, **kwargs) -> dict`. Errors are caught at the registry boundary and returned as `{"error": "...", "hint": "..."}` so the model can recover. Each tool result is capped at 4 KB serialized JSON; longer results return a truncation notice.

- [ ] **Step 1: Write the failing tests**

Create `services/api/tests/test_coach_tools.py`:

```python
"""Coach tool registry + per-tool unit tests."""
import json

import pytest

from app.services.coach.tools import (
    REGISTRY,
    ToolError,
    dispatch,
    schema_for_llm,
)


def test_schema_for_llm_lists_all_registered_tools():
    schemas = schema_for_llm()
    names = [s["function"]["name"] for s in schemas]
    # Slice 2 tool set:
    assert "trend" in names
    assert "compare_windows" in names
    assert "food_history" in names
    assert "recall" in names


async def test_dispatch_unknown_tool_returns_error(mock_db):
    out = await dispatch(mock_db, "no_such_tool", {})
    assert "error" in out
    assert "unknown" in out["error"].lower()


async def test_dispatch_caps_oversized_results(mock_db, monkeypatch):
    """A tool returning a huge dict gets truncated with a `_truncated` flag."""
    async def big_tool(_db, **_kwargs):
        return {"data": ["x" * 100] * 100}  # ~10KB serialized
    monkeypatch.setitem(REGISTRY, "big_tool", {
        "fn": big_tool,
        "schema": {"type": "function", "function": {"name": "big_tool", "description": "test"}},
    })
    out = await dispatch(mock_db, "big_tool", {})
    serialized = json.dumps(out)
    assert len(serialized) <= 4500  # 4KB cap + some slack for truncation marker
    assert out.get("_truncated") is True


async def test_dispatch_wraps_tool_exceptions_as_errors(mock_db, monkeypatch):
    async def boom_tool(_db, **_kwargs):
        raise ToolError("intentional explosion")
    monkeypatch.setitem(REGISTRY, "boom_tool", {
        "fn": boom_tool,
        "schema": {"type": "function", "function": {"name": "boom_tool", "description": "test"}},
    })
    out = await dispatch(mock_db, "boom_tool", {})
    assert "error" in out
    assert "intentional explosion" in out["error"]
```

- [ ] **Step 2: Run them to verify they fail**

```
cd services/api && .venv/bin/pytest tests/test_coach_tools.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the registry skeleton + four tool stubs**

Create `services/api/app/services/coach/tools.py`:

```python
"""Coach tool registry — dispatch by name, cap result size, wrap errors.

Each tool is an async function `(db, **kwargs) -> dict`. The LLM gets
`schema_for_llm()` to call them by name with JSON args. Tool errors
return `{"error": "...", "hint": "..."}` so the model can recover.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from pymongo.asynchronous.database import AsyncDatabase

logger = logging.getLogger(__name__)

# 4KB hard cap on tool results so the model context stays bounded.
RESULT_BYTE_CAP = 4096


class ToolError(Exception):
    """Raise inside a tool to surface a friendly error to the model."""


REGISTRY: dict[str, dict[str, Any]] = {}


def _truncate(result: dict[str, Any]) -> dict[str, Any]:
    serialized = json.dumps(result, default=str)
    if len(serialized) <= RESULT_BYTE_CAP:
        return result
    return {
        "_truncated": True,
        "_note": (
            f"result exceeded {RESULT_BYTE_CAP}B and was truncated; "
            "narrow your query or pass a smaller window"
        ),
        "preview": serialized[: RESULT_BYTE_CAP - 200],
    }


async def dispatch(
    db: AsyncDatabase, name: str, args: dict[str, Any],
) -> dict[str, Any]:
    """Call a registered tool by name with kwargs. Errors are caught."""
    entry = REGISTRY.get(name)
    if entry is None:
        return {
            "error": f"unknown tool: {name!r}",
            "hint": f"available: {sorted(REGISTRY.keys())}",
        }
    try:
        result = await entry["fn"](db, **args)
    except ToolError as e:
        return {"error": str(e)}
    except TypeError as e:
        return {"error": f"bad arguments: {e}"}
    except Exception:
        logger.exception("tool %s crashed", name)
        return {"error": f"tool {name!r} crashed (logged server-side)"}
    return _truncate(result)


def schema_for_llm() -> list[dict[str, Any]]:
    """Return Ollama-compatible tool schemas for every registered tool."""
    return [entry["schema"] for entry in REGISTRY.values()]


# --- Tool stubs (filled in by Tasks 5-8) ---------------------------------

async def _trend(db: AsyncDatabase, **_kwargs) -> dict[str, Any]:  # noqa: ARG001
    raise ToolError("trend not implemented yet")

async def _compare_windows(db: AsyncDatabase, **_kwargs) -> dict[str, Any]:  # noqa: ARG001
    raise ToolError("compare_windows not implemented yet")

async def _food_history(db: AsyncDatabase, **_kwargs) -> dict[str, Any]:  # noqa: ARG001
    raise ToolError("food_history not implemented yet")

async def _recall(db: AsyncDatabase, **_kwargs) -> dict[str, Any]:  # noqa: ARG001
    return {"memories": []}  # Slice 4 wires this to a real store.


REGISTRY.update({
    "trend": {
        "fn": _trend,
        "schema": {
            "type": "function",
            "function": {
                "name": "trend",
                "description": "Summarize a metric over the last N days (avg, slope per day, first, last).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "metric": {"type": "string", "enum": ["hrv", "weight", "sleep_score", "steps"]},
                        "window_days": {"type": "integer", "minimum": 2, "maximum": 90},
                    },
                    "required": ["metric", "window_days"],
                },
            },
        },
    },
    "compare_windows": {
        "fn": _compare_windows,
        "schema": {
            "type": "function",
            "function": {
                "name": "compare_windows",
                "description": "Compare a metric's recent window to an earlier baseline window. Returns abs and pct delta.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "metric": {"type": "string", "enum": ["hrv", "weight", "sleep_score", "steps"]},
                        "recent_days": {"type": "integer", "minimum": 1, "maximum": 30},
                        "baseline_days": {"type": "integer", "minimum": 7, "maximum": 90},
                    },
                    "required": ["metric", "recent_days", "baseline_days"],
                },
            },
        },
    },
    "food_history": {
        "fn": _food_history,
        "schema": {
            "type": "function",
            "function": {
                "name": "food_history",
                "description": "Daily calorie and macro totals over a date range (UTC dates, YYYY-MM-DD).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "start_date": {"type": "string", "description": "YYYY-MM-DD"},
                        "end_date": {"type": "string", "description": "YYYY-MM-DD inclusive"},
                    },
                    "required": ["start_date", "end_date"],
                },
            },
        },
    },
    "recall": {
        "fn": _recall,
        "schema": {
            "type": "function",
            "function": {
                "name": "recall",
                "description": "Recall durable facts the client has told the coach. Returns list of {key, value}.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "specific fact key, omit for all"},
                    },
                },
            },
        },
    },
})
```

- [ ] **Step 4: Run the tests**

```
cd services/api && .venv/bin/pytest tests/test_coach_tools.py -v
```

Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/coach/tools.py services/api/tests/test_coach_tools.py
git commit -m "feat(coach): tool registry skeleton (dispatch/schema_for_llm) + 4 tool stubs"
```

---

### Task 5: Implement `trend` tool

**Files:**
- Modify: `services/api/app/services/coach/tools.py`
- Modify: `services/api/tests/test_coach_tools.py`

`trend` fetches the metric series for the requested window and runs the existing `context.trend()` helper. Supported metrics: hrv, weight, sleep_score, steps.

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_coach_tools.py`:

```python
from datetime import UTC, datetime, timedelta

from app.models.metrics import HRV, Weight
from app.services.coach.tools import dispatch
from app.services.metrics_repo import MetricsRepo


async def test_trend_tool_returns_hrv_summary(mock_db):
    repo = MetricsRepo(mock_db)
    now = datetime.now(UTC)
    for i in range(7, 0, -1):
        await repo.insert_hrv(HRV(
            ts=now - timedelta(days=i),
            rmssd_ms=50.0 + i,  # 51..57
            source="garmin", source_id=f"h:{i}",
        ))
    out = await dispatch(mock_db, "trend", {"metric": "hrv", "window_days": 7})
    assert "error" not in out, out
    assert out["count"] == 7
    assert out["avg"] is not None


async def test_trend_tool_returns_weight_summary(mock_db):
    repo = MetricsRepo(mock_db)
    now = datetime.now(UTC)
    for i in range(7, 0, -1):
        await repo.insert_weight(Weight(
            ts=now - timedelta(days=i),
            kg=108.0,
            source="garmin", source_id=f"w:{i}",
        ))
    out = await dispatch(mock_db, "trend", {"metric": "weight", "window_days": 7})
    assert out["count"] == 7
    assert out["avg"] == 108.0


async def test_trend_tool_rejects_unknown_metric(mock_db):
    out = await dispatch(mock_db, "trend", {"metric": "bogus", "window_days": 7})
    assert "error" in out
```

- [ ] **Step 2: Run to verify they fail**

```
cd services/api && .venv/bin/pytest tests/test_coach_tools.py -v
```

Expected: 3 new FAIL with "trend not implemented yet" (from the stub).

- [ ] **Step 3: Implement `_trend`**

Replace the `_trend` stub in `services/api/app/services/coach/tools.py` with:

```python
async def _trend(
    db: AsyncDatabase, *, metric: str, window_days: int,
) -> dict[str, Any]:
    from datetime import UTC, datetime, timedelta

    from app.services.coach.context import trend as _trend_helper
    from app.services.metrics_repo import MetricsRepo

    if metric not in {"hrv", "weight", "sleep_score", "steps"}:
        raise ToolError(f"unknown metric {metric!r}")
    repo = MetricsRepo(db)
    now = datetime.now(UTC)
    start = now - timedelta(days=window_days)
    if metric == "hrv":
        series = await repo.range_hrv(start, now)
        return _trend_helper(series, value_key="rmssd_ms")
    if metric == "weight":
        series = await repo.range_weight(start, now)
        return _trend_helper(series, value_key="kg")
    if metric == "sleep_score":
        series = await repo.range_sleep(start, now)
        return _trend_helper(series, value_key="score")
    # steps
    series = await repo.range_daily_summary(start, now)
    return _trend_helper(series, value_key="steps")
```

- [ ] **Step 4: Run tests**

```
cd services/api && .venv/bin/pytest tests/test_coach_tools.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/coach/tools.py services/api/tests/test_coach_tools.py
git commit -m "feat(coach): implement trend tool over hrv/weight/sleep_score/steps"
```

---

### Task 6: Implement `compare_windows` tool

**Files:**
- Modify: `services/api/app/services/coach/tools.py`
- Modify: `services/api/tests/test_coach_tools.py`

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_coach_tools.py`:

```python
async def test_compare_windows_tool_returns_delta(mock_db):
    repo = MetricsRepo(mock_db)
    now = datetime.now(UTC)
    # Last 7 days: 40, prior 30 days: 60 → recent avg lower.
    for i in range(7, 0, -1):
        await repo.insert_hrv(HRV(
            ts=now - timedelta(days=i), rmssd_ms=40.0,
            source="garmin", source_id=f"h-recent:{i}",
        ))
    for i in range(30, 7, -1):
        await repo.insert_hrv(HRV(
            ts=now - timedelta(days=i), rmssd_ms=60.0,
            source="garmin", source_id=f"h-prior:{i}",
        ))
    out = await dispatch(mock_db, "compare_windows", {
        "metric": "hrv", "recent_days": 7, "baseline_days": 30,
    })
    assert "error" not in out, out
    assert out["recent_avg"] == 40.0
    assert out["prior_avg"] == 60.0
    assert out["abs"] == -20.0
```

- [ ] **Step 2: Run to verify it fails**

```
cd services/api && .venv/bin/pytest tests/test_coach_tools.py::test_compare_windows_tool_returns_delta -v
```

Expected: FAIL with "compare_windows not implemented yet".

- [ ] **Step 3: Implement `_compare_windows`**

Replace the `_compare_windows` stub:

```python
async def _compare_windows(
    db: AsyncDatabase, *, metric: str, recent_days: int, baseline_days: int,
) -> dict[str, Any]:
    from datetime import UTC, datetime, timedelta

    from app.services.coach.context import delta as _delta_helper
    from app.services.metrics_repo import MetricsRepo

    if metric not in {"hrv", "weight", "sleep_score", "steps"}:
        raise ToolError(f"unknown metric {metric!r}")
    if baseline_days <= recent_days:
        raise ToolError("baseline_days must be greater than recent_days")
    repo = MetricsRepo(db)
    now = datetime.now(UTC)
    recent_start = now - timedelta(days=recent_days)
    baseline_start = now - timedelta(days=baseline_days)
    baseline_end = recent_start  # prior window ends where recent begins
    if metric == "hrv":
        recent = await repo.range_hrv(recent_start, now)
        prior = await repo.range_hrv(baseline_start, baseline_end)
        return _delta_helper(recent, prior, value_key="rmssd_ms")
    if metric == "weight":
        recent = await repo.range_weight(recent_start, now)
        prior = await repo.range_weight(baseline_start, baseline_end)
        return _delta_helper(recent, prior, value_key="kg")
    if metric == "sleep_score":
        recent = await repo.range_sleep(recent_start, now)
        prior = await repo.range_sleep(baseline_start, baseline_end)
        return _delta_helper(recent, prior, value_key="score")
    # steps
    recent = await repo.range_daily_summary(recent_start, now)
    prior = await repo.range_daily_summary(baseline_start, baseline_end)
    return _delta_helper(recent, prior, value_key="steps")
```

- [ ] **Step 4: Run tests**

```
cd services/api && .venv/bin/pytest tests/test_coach_tools.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/coach/tools.py services/api/tests/test_coach_tools.py
git commit -m "feat(coach): implement compare_windows tool"
```

---

### Task 7: Implement `food_history` tool

**Files:**
- Modify: `services/api/app/services/coach/tools.py`
- Modify: `services/api/tests/test_coach_tools.py`

Returns a list of daily totals (calories + macros) over the requested UTC date range, capped at 30 days for safety.

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_coach_tools.py`:

```python
async def test_food_history_tool_returns_daily_totals(mock_db):
    base = datetime(2026, 4, 26, 12, 0, tzinfo=UTC)
    for day_offset, cal in enumerate([1800.0, 2000.0, 2100.0]):
        await mock_db["meal_entries"].insert_one({
            "ts": base + timedelta(days=day_offset),
            "food_name": "Test", "quantity_g": 100, "slot": "dinner",
            "macros": {"calories": cal, "protein_g": 100, "carbs_g": 200, "fat_g": 50},
        })
    out = await dispatch(mock_db, "food_history", {
        "start_date": "2026-04-26", "end_date": "2026-04-28",
    })
    assert "error" not in out, out
    assert len(out["days"]) == 3
    assert out["days"][0]["date"] == "2026-04-26"
    assert out["days"][0]["calories"] == 1800.0


async def test_food_history_tool_caps_range_at_30_days(mock_db):
    out = await dispatch(mock_db, "food_history", {
        "start_date": "2026-01-01", "end_date": "2026-04-01",  # ~90 days
    })
    assert "error" in out
    assert "30" in out["error"]


async def test_food_history_tool_handles_bad_date(mock_db):
    out = await dispatch(mock_db, "food_history", {
        "start_date": "not-a-date", "end_date": "2026-04-28",
    })
    assert "error" in out
```

- [ ] **Step 2: Run to verify they fail**

```
cd services/api && .venv/bin/pytest tests/test_coach_tools.py -v
```

Expected: 3 new FAIL with "food_history not implemented yet" (or arg error).

- [ ] **Step 3: Implement `_food_history`**

Replace the `_food_history` stub:

```python
async def _food_history(
    db: AsyncDatabase, *, start_date: str, end_date: str,
) -> dict[str, Any]:
    from datetime import UTC, datetime, timedelta

    try:
        start = datetime.fromisoformat(start_date).replace(tzinfo=UTC)
        end = datetime.fromisoformat(end_date).replace(tzinfo=UTC)
    except ValueError as e:
        raise ToolError(f"bad date format (use YYYY-MM-DD): {e}") from e
    if end < start:
        raise ToolError("end_date must be >= start_date")
    days = (end - start).days + 1
    if days > 30:
        raise ToolError("range too long; max 30 days")
    # Pull all entries in the range (inclusive of end day).
    end_exclusive = end + timedelta(days=1)
    cur = db["meal_entries"].find({"ts": {"$gte": start, "$lt": end_exclusive}})
    by_date: dict[str, dict[str, float]] = {}
    async for e in cur:
        d = e["ts"].astimezone(UTC).date().isoformat()
        bucket = by_date.setdefault(d, {
            "calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0,
        })
        m = e.get("macros") or {}
        for k in bucket:
            v = m.get(k)
            if v is not None:
                bucket[k] += float(v)
    out_days = [
        {"date": (start + timedelta(days=i)).date().isoformat(),
         **by_date.get((start + timedelta(days=i)).date().isoformat(), {
             "calories": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0,
         })}
        for i in range(days)
    ]
    return {"days": out_days}
```

- [ ] **Step 4: Run tests**

```
cd services/api && .venv/bin/pytest tests/test_coach_tools.py -v
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/coach/tools.py services/api/tests/test_coach_tools.py
git commit -m "feat(coach): implement food_history tool (daily macro totals over a range)"
```

---

### Task 8: Chat agent loop driver

**Files:**
- Create: `services/api/app/services/coach/chat.py`
- Create: `services/api/tests/test_coach_chat.py`

The driver takes a `db`, a `thread_id`, and a `user_message`. It:
1. Loads thread turns + current Findings (deterministic snapshot for grounding).
2. Builds a `messages` array for Ollama `/api/chat`: system, optional findings preamble, then each prior turn as `{role, content}`, then the new user message.
3. Loops: POST `/api/chat` with `tools=schema_for_llm()`. If the response has `tool_calls`, dispatch each, append tool results as `{role: "tool", content: <json>}`, and repeat. If `content` is non-empty, that's the final reply.
4. Cap at 6 iterations. On cap, force a synthetic final coach turn ("hit tool-call limit, here's what I have…").
5. Appends turns to the thread: user turn first, then coach turn (with `tool_calls` metadata).
6. Returns the coach turn.

The driver does NOT modify the brief path; it's a separate code path.

- [ ] **Step 1: Write the failing test (mock Ollama with a 2-step tool-call → final-reply state machine)**

Create `services/api/tests/test_coach_chat.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

```
cd services/api && .venv/bin/pytest tests/test_coach_chat.py -v
```

Expected: FAIL — `app.services.coach.chat` does not exist.

- [ ] **Step 3: Implement the chat driver**

Create `services/api/app/services/coach/chat.py`:

```python
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

from app.config import Settings
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
    settings: Settings, db: AsyncDatabase, thread_id: str, *, user_message: str,
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
```

- [ ] **Step 4: Run the tests**

```
cd services/api && .venv/bin/pytest tests/test_coach_chat.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Run the full suite to catch indirect breakage**

```
cd services/api && .venv/bin/pytest -q
```

Expected: ~226 PASS (prior + 5 threads + 1 thread-creation + 1 thread-active + 11 tools + 3 chat).

- [ ] **Step 6: Commit**

```bash
git add services/api/app/services/coach/chat.py services/api/tests/test_coach_chat.py
git commit -m "feat(coach): chat agent loop driver (bounded tool use via Ollama /api/chat)"
```

---

### Task 9: `POST /coach/thread/{id}/reply` endpoint

**Files:**
- Modify: `services/api/app/routers/coach.py`
- Modify: `services/api/tests/test_coach.py`

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_coach.py`:

```python
async def test_thread_reply_runs_agent_and_returns_coach_turn(
    client, mock_db, fake_ollama_response,
):
    """POST /coach/thread/{id}/reply runs the chat driver and returns
    the new coach turn (text + any tool_calls)."""
    await _seed(mock_db)

    # First, create a thread by generating a brief.
    async def _fake_generate(_self, _url, json=None):
        del json
        class _R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return fake_ollama_response
        return _R()

    with patch.object(httpx.AsyncClient, "post", _fake_generate):
        r = await client.get("/coach/insight", headers=HEADERS)
    thread_id = r.json()["thread_id"]

    # Mock /api/chat with a single-iteration final response.
    chat_response = {
        "message": {"role": "assistant", "content": "Sleep was fine.", "tool_calls": []},
    }
    async def _fake_chat(_self, _url, json=None):
        del json
        class _R:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return chat_response
        return _R()

    with patch.object(httpx.AsyncClient, "post", _fake_chat):
        r = await client.post(
            f"/coach/thread/{thread_id}/reply", headers=HEADERS,
            json={"text": "tell me about sleep"},
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["role"] == "coach"
    assert "Sleep was fine" in body["text"]


async def test_thread_reply_404_when_thread_missing(client):
    r = await client.post(
        "/coach/thread/000000000000000000000000/reply",
        headers=HEADERS, json={"text": "hi"},
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run to verify they fail**

```
cd services/api && .venv/bin/pytest tests/test_coach.py::test_thread_reply_runs_agent_and_returns_coach_turn tests/test_coach.py::test_thread_reply_404_when_thread_missing -v
```

Expected: FAIL — endpoint not defined (404 on unknown path).

- [ ] **Step 3: Add the endpoint to `services/api/app/routers/coach.py`**

Add the request model near `FeedbackReq`:

```python
class ReplyReq(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
```

Add the route handler after `thread_active`:

```python
@router.post("/thread/{thread_id}/reply")
async def thread_reply(
    thread_id: str, req: ReplyReq, request: Request,
) -> dict[str, Any]:
    """Run one user→coach turn through the chat agent loop and return
    the new coach turn (text + any tool_calls used)."""
    from app.services.coach.chat import reply as chat_reply
    from app.services.coach.threads import get_thread
    db = request.app.state.db
    _oid(thread_id)  # validate id shape, will 400 on bad input
    if await get_thread(db, thread_id) is None:
        raise HTTPException(status_code=404, detail="thread not found")
    settings = request.app.state.settings
    try:
        turn = await chat_reply(settings, db, thread_id, user_message=req.text)
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"coach LLM unavailable: {type(e).__name__}: {e}",
        ) from e
    # Ensure timestamps are JSON-serializable.
    if isinstance(turn.get("ts"), datetime):
        turn["ts"] = turn["ts"].isoformat()
    return turn
```

- [ ] **Step 4: Run the new tests**

```
cd services/api && .venv/bin/pytest tests/test_coach.py::test_thread_reply_runs_agent_and_returns_coach_turn tests/test_coach.py::test_thread_reply_404_when_thread_missing -v
```

Expected: PASS.

- [ ] **Step 5: Run the full suite**

```
cd services/api && .venv/bin/pytest -q
```

Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add services/api/app/routers/coach.py services/api/tests/test_coach.py
git commit -m "feat(coach): add POST /coach/thread/{id}/reply endpoint"
```

---

### Task 10: Re-export new public surface from `coach/__init__.py`

**Files:**
- Modify: `services/api/app/services/coach/__init__.py`

- [ ] **Step 1: Update the package's re-exports**

Replace `services/api/app/services/coach/__init__.py` with:

```python
"""Coach package — brief generation, chat agent loop, tools, threads.

The router and scheduler import everything they need from this top-level
namespace so that callers don't have to know which submodule a thing
lives in.
"""
from app.services.coach.brief import (  # noqa: F401
    RECENT_LIMIT,
    SYSTEM_PROMPT,
    USER_PROFILE,
    Insight,
    gather_context,
    generate_insight,
    recent_insights,
    resolve_day_window,
    save_insight,
    today_food_totals,
)
from app.services.coach.chat import MAX_ITERATIONS, reply  # noqa: F401
from app.services.coach.threads import (  # noqa: F401
    Turn,
    append_turn,
    create_thread,
    get_active_thread,
    get_thread,
)
from app.services.coach.tools import (  # noqa: F401
    REGISTRY,
    ToolError,
    dispatch,
    schema_for_llm,
)
```

- [ ] **Step 2: Run the suite**

```
cd services/api && .venv/bin/pytest -q
```

Expected: same PASS count (no behavior change; pure re-exports).

- [ ] **Step 3: Commit**

```bash
git add services/api/app/services/coach/__init__.py
git commit -m "refactor(coach): re-export threads/chat/tools from package __init__"
```

---

### Task 11: FE types for thread + turn + reply

**Files:**
- Modify: `services/web/src/api/types.ts`

- [ ] **Step 1: Find the existing CoachInsight type and add new types after it**

Open `services/web/src/api/types.ts`. After the existing `CoachInsight`, `CoachRecentEntry`, and related types, add:

```typescript
export interface CoachToolCall {
  name: string;
  args: Record<string, unknown>;
  result: Record<string, unknown>;
}

export interface CoachTurn {
  role: "coach" | "user";
  text: string;
  ts: string;
  tool_calls?: CoachToolCall[] | null;
  findings_snapshot?: Record<string, unknown> | null;
}

export interface CoachThread {
  id: string;
  started_at: string;
  last_activity_at: string;
  surface: string;
  turns: CoachTurn[];
}

export interface CoachReplyRequest {
  text: string;
}
```

Also update `CoachInsight` to include the new optional `thread_id` field (find the existing interface and append):

```typescript
export interface CoachInsight {
  // ... existing fields ...
  thread_id?: string | null;
}
```

(If `CoachInsight` already has fields like `id`, `text`, `model`, etc., add `thread_id?: string | null;` as a new line inside the interface body. Don't duplicate existing fields.)

- [ ] **Step 2: Run the FE build to verify types compile**

```
cd services/web && npx tsc -b --noEmit
```

Expected: clean (no type errors).

- [ ] **Step 3: Commit**

```bash
git add services/web/src/api/types.ts
git commit -m "feat(web): add CoachThread/Turn types for chat panel"
```

---

### Task 12: FE api client methods for threads + reply

**Files:**
- Modify: `services/web/src/api/client.ts`

- [ ] **Step 1: Add imports and methods**

In `services/web/src/api/client.ts`, add `CoachThread, CoachTurn` to the existing type import block at the top of the file.

Then in the `export const api = { ... }` object, add two new methods (e.g. after `coachWeekly`):

```typescript
  coachThreadActive: async (): Promise<CoachThread | null> => {
    try {
      return await get<CoachThread>("/coach/thread/active");
    } catch (e) {
      if ((e as Error).message?.includes(" 404")) return null;
      throw e;
    }
  },
  coachThreadReply: (threadId: string, text: string) =>
    post<CoachTurn>(`/coach/thread/${threadId}/reply`, { text }),
```

- [ ] **Step 2: Typecheck**

```
cd services/web && npx tsc -b --noEmit
```

Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add services/web/src/api/client.ts
git commit -m "feat(web): api.coachThreadActive + api.coachThreadReply"
```

---

### Task 13: `CoachChatPanel` component

**Files:**
- Create: `services/web/src/components/CoachChatPanel.tsx`
- Create: `services/web/src/components/CoachChatPanel.test.tsx`

The panel loads the active thread, renders each turn, and provides an input. Submitting calls `coachThreadReply` and re-fetches the thread.

- [ ] **Step 1: Write a minimal failing test**

Create `services/web/src/components/CoachChatPanel.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { CoachChatPanel } from "./CoachChatPanel";
import { api } from "../api/client";

vi.mock("../api/client", () => ({
  api: {
    coachThreadActive: vi.fn().mockResolvedValue({
      id: "tid1",
      started_at: "2026-05-10T12:00:00Z",
      last_activity_at: "2026-05-10T12:00:00Z",
      surface: "web",
      turns: [
        { role: "coach", text: "Sleep solid.", ts: "2026-05-10T12:00:00Z" },
      ],
    }),
    coachThreadReply: vi.fn(),
  },
}));

function wrap(node: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

describe("CoachChatPanel", () => {
  it("renders the first coach turn from the active thread", async () => {
    render(wrap(<CoachChatPanel />));
    expect(await screen.findByText(/sleep solid/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```
cd services/web && npm test -- --run src/components/CoachChatPanel.test.tsx
```

Expected: FAIL — component does not exist.

- [ ] **Step 3: Implement the component**

Create `services/web/src/components/CoachChatPanel.tsx`:

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { CoachTurn } from "../api/types";


function TurnBubble({ turn }: { turn: CoachTurn }) {
  const isCoach = turn.role === "coach";
  return (
    <div className={isCoach ? "text-sm text-neutral-200" : "text-sm text-emerald-300"}>
      <div className="text-[10px] uppercase tracking-wide text-neutral-500 mb-0.5">
        {isCoach ? "Coach" : "You"}
      </div>
      <div className="whitespace-pre-wrap leading-relaxed">{turn.text}</div>
      {turn.tool_calls?.length ? (
        <details className="text-[11px] text-neutral-500 mt-1">
          <summary className="cursor-pointer">
            {turn.tool_calls.length} tool call{turn.tool_calls.length > 1 ? "s" : ""}
          </summary>
          <ul className="pl-2 font-mono space-y-1 mt-1">
            {turn.tool_calls.map((c, i) => (
              <li key={i}>{c.name}({JSON.stringify(c.args)})</li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

export function CoachChatPanel() {
  const qc = useQueryClient();
  const [draft, setDraft] = useState("");
  const { data: thread, isLoading } = useQuery({
    queryKey: ["coach.thread.active"],
    queryFn: () => api.coachThreadActive(),
  });

  const send = useMutation({
    mutationFn: async (text: string) => {
      if (!thread) throw new Error("no active thread");
      return api.coachThreadReply(thread.id, text);
    },
    onSuccess: () => {
      setDraft("");
      void qc.invalidateQueries({ queryKey: ["coach.thread.active"] });
    },
  });

  if (isLoading) {
    return <div className="text-xs text-neutral-500">loading thread…</div>;
  }
  if (!thread) {
    return (
      <div className="text-xs text-neutral-500">
        no active thread — ask the coach above to start one.
      </div>
    );
  }

  return (
    <div className="space-y-3 border-t border-neutral-800 pt-3">
      <div className="space-y-3 max-h-[40vh] overflow-y-auto">
        {thread.turns.map((t, i) => (
          <TurnBubble key={i} turn={t} />
        ))}
        {send.isPending && (
          <div className="text-xs text-neutral-500 italic">coach thinking…</div>
        )}
      </div>
      <form
        onSubmit={e => { e.preventDefault(); if (draft.trim()) send.mutate(draft.trim()); }}
        className="flex gap-2"
      >
        <input
          type="text"
          value={draft}
          onChange={e => setDraft(e.target.value)}
          placeholder="ask the coach…"
          disabled={send.isPending}
          className="flex-1 text-sm px-3 py-2 rounded bg-neutral-800 border border-neutral-700 text-neutral-100 placeholder:text-neutral-500"
        />
        <button
          type="submit"
          disabled={send.isPending || !draft.trim()}
          className="text-xs px-3 py-2 rounded bg-emerald-700 active:bg-emerald-800 disabled:opacity-50"
        >
          send
        </button>
      </form>
      {send.error && (
        <div className="text-xs text-red-400">{(send.error as Error).message}</div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the test**

```
cd services/web && npm test -- --run src/components/CoachChatPanel.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Run the full FE suite**

```
cd services/web && npm test -- --run
```

Expected: all PASS (existing tests untouched plus the new one).

- [ ] **Step 6: Commit**

```bash
git add services/web/src/components/CoachChatPanel.tsx services/web/src/components/CoachChatPanel.test.tsx
git commit -m "feat(web): CoachChatPanel — render active thread + reply input"
```

---

### Task 14: Wire `CoachChatPanel` into `CoachCard`

**Files:**
- Modify: `services/web/src/components/CoachCard.tsx`

- [ ] **Step 1: Add the import**

At the top of `services/web/src/components/CoachCard.tsx`, add:

```tsx
import { CoachChatPanel } from "./CoachChatPanel";
```

- [ ] **Step 2: Render the chat panel inside the expanded view**

Inside the `return (...)` block of `CoachCard()` (the expanded view, the one with the `<div className="rounded-xl bg-neutral-900 ...">` wrapper), add `<CoachChatPanel />` after the existing `<CoachBody />` and `{showHistory && <HistoryList .../>}` block. The end of that return should look like:

```tsx
      <CoachBody display={display} error={weekly.error ?? ask.error} />

      {showHistory && <HistoryList items={history?.slice(1) ?? []} />}

      <CoachChatPanel />
    </div>
  );
}
```

- [ ] **Step 3: Run the FE tests**

```
cd services/web && npm test -- --run
```

Expected: all PASS.

- [ ] **Step 4: Typecheck**

```
cd services/web && npx tsc -b --noEmit
```

Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add services/web/src/components/CoachCard.tsx
git commit -m "feat(web): render CoachChatPanel below brief in expanded CoachCard"
```

---

### Task 15: Final verification and push

- [ ] **Step 1: Run the full backend suite**

```
cd services/api && .venv/bin/pytest -q
```

Expected: all PASS. (Baseline 209 → ~230 after this slice.)

- [ ] **Step 2: Lint backend**

```
cd services/api && .venv/bin/ruff check app tests
```

Expected: 1 pre-existing error in `tests/test_treadmill_aggregator.py:189` (the baseline). Zero new errors.

If new errors appear, fix them inline before pushing. Common ones for this slice:
- `PLC0415` (function-local import) — add `# noqa: PLC0415` if the import is deliberately deferred (e.g. inside `dispatch`'s tool stubs in `tools.py`).
- `E402` (import not at top of file) — move test imports to the top of test files.
- `PLR2004` (magic value) — extract to module-level constants.

- [ ] **Step 3: Run the full FE suite**

```
cd services/web && npm test -- --run
```

Expected: all PASS.

- [ ] **Step 4: FE typecheck**

```
cd services/web && npx tsc -b --noEmit
```

Expected: clean.

- [ ] **Step 5: Smoke-test end-to-end against the local LLM (optional but recommended)**

Start the API + Ollama. Hit the dashboard, expand the Coach card, type a question into the chat input, and observe:
- The thread loads with the brief as turn 1.
- After submit, the input clears, a "coach thinking…" appears briefly, then a new coach turn renders.
- If the model used tools, the `N tool calls` details element appears and lists them.

If the LLM doesn't emit tool_calls in its response (e.g. you're on a model that doesn't support tool calling in Ollama), the chat path still works — it'll just produce direct text replies without invoking any tool.

- [ ] **Step 6: Push**

```bash
git push origin master
```

Watchtower picks up the rebuilt image on `hd` (~60s) and the chat panel lights up on the next dashboard load.

---

## Self-Review

**Spec coverage**

Slice 2 from the spec: "Threads + chat panel + tool loop. Brief becomes turn 1; chat panel under the brief; tool registry online with `trend`, `compare_windows`, `food_history`, `recall`."

- Threads collection (`coach_threads`) — Task 1 (repo) + Task 2 (brief writes turn 1) + Task 3 (active endpoint).
- Chat panel — Tasks 11-14.
- Tool registry with the four tools — Tasks 4-7 (`recall` is a stub returning `{memories: []}` per the spec's Slice 4 wiring; the tool is callable today, just produces no data).
- Tool loop — Task 8 (`chat.py`) + Task 9 (`POST /coach/thread/{id}/reply`).
- Iteration cap (6) — covered in Task 8's `MAX_ITERATIONS` + the cap test.
- Tool error wrapping — covered in Task 4's `dispatch` and the wrap test.
- 4 KB result cap — covered in Task 4's `_truncate` and the cap test.

**Deferred from this slice (explicitly):**
- Mid-thread-turn feedback (`coach_feedback` keyed by `(thread_id, turn_index)`). The spec mentions it but feedback continues to work against the turn-1 insight, which is enough for now.
- Thread-close timer (idle >2h) and implicit extraction — Slice 5.
- Feature flag `COACH_V2_ENABLED` — single-user repo; ship behind nothing.
- Thread listing (`GET /coach/threads?limit=`) — chat panel only needs `/active` for now.
- `mark_habit_done` and `habit_status` tools — Slice 3.
- `remember` and the explicit-memory store — Slice 4.

**Placeholder scan**

- No "TBD" / "TODO" / "fill in" anywhere.
- Every code step has actual code.
- Every command has expected output.

**Type consistency**

- `Turn` defined in Task 1 (`role: "coach"|"user"`, `text`, `tool_calls?`, `findings_snapshot?`, `ts`). Used in Tasks 2, 8, 9.
- `Thread` shape (`_id`, `started_at`, `last_activity_at`, `closed_at`, `surface`, `turns`) consistent across Tasks 1, 3, 8.
- `dispatch(db, name, args)` consistent in Tasks 4, 5, 6, 7, 8.
- Tool argument names match between schemas (Task 4) and implementations (Tasks 5-7): `metric, window_days`, `metric, recent_days, baseline_days`, `start_date, end_date`.
- `reply(settings, db, thread_id, *, user_message)` signature consistent between Task 8 and Task 9.
- FE `CoachThread` / `CoachTurn` (Task 11) match the JSON shape produced by Tasks 3 and 9.
