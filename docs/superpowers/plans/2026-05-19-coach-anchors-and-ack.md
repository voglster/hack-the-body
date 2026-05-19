# Coach Time Anchors + Brief Acknowledgment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Coach output emits structured `anchors` so the browser renders a live, accurate relative time, and users can acknowledge a brief from web or kiosk (Home Assistant via HTTP) so subsequent same-surface generations stop restating already-seen points.

**Architecture:** The brief and kiosk endpoints both return a JSON-structured payload with `text` containing `{{name}}` placeholders and `anchors: dict[name, ISO]`. The brief LLM call switches to JSON response mode; the kiosk JSON gains an `anchors` field. Server stores `anchors` and `acked_at` on the `coach_insights` doc. New POST endpoints flip `acked_at`. Generation history flows the acked flag back into the prompt; surface-scoped history queries keep web and kiosk independent. FE adds a `useNow` hook + `<CoachText>` component that splits on placeholders and renders live `<RelativeAnchor>` children; CoachCard and KioskCoachLine gain ack affordances.

**Tech Stack:** FastAPI (Python 3.12) + Motor/AsyncDatabase Mongo, React 18 + TanStack Query + Vite (TypeScript), pytest, vitest.

---

## File Structure

**Backend — modify:**
- `services/api/app/services/coach/brief.py` — `Insight` dataclass adds `anchors`; `save_insight`/`recent_insights` carry it; `BRIEF_SYSTEM_PROMPT` and `KIOSK_SYSTEM_PROMPT` document anchors; `generate_insight` parses JSON for brief (currently prose) and forwards anchors to the dataclass; `recent_insights` gains surface scoping for history.
- `services/api/app/routers/coach.py` — `_serialize` returns `anchors` and `acked_at`; kiosk handler reads `anchors` from parsed JSON; three new endpoints: `POST /coach/insights/{id}/ack`, `POST /coach/ack/web-latest`, `POST /coach/ack/kiosk-latest`.

**Backend — create:**
- `services/api/tests/test_coach_anchors.py` — anchor round-trip + prompt-shape tests.
- `services/api/tests/test_coach_ack.py` — ack endpoint behavior + history flag.

**Frontend — modify:**
- `services/web/src/api/types.ts` — `CoachInsight`, `KioskGlance`, `CoachRecentEntry` gain `anchors?: Record<string,string> | null` and `acked_at?: string | null`.
- `services/web/src/api/client.ts` — add `coachAck`, `coachAckWebLatest`, `coachAckKioskLatest`.
- `services/web/src/components/CoachCard.tsx` — replace plaintext rendering of `display.text` with `<CoachText>`; add ✓ ack button on the expanded card; show acknowledged state when `acked_at` is set.
- `services/web/src/components/kiosk/KioskCoachLine.tsx` — render `coach` text through `<CoachText>` using `anchors`; add a kiosk-style ack button beneath the line.

**Frontend — create:**
- `services/web/src/lib/useNow.ts` — `useNow(intervalMs?)` hook returning a `Date` that re-renders subscribers on an interval.
- `services/web/src/components/CoachText.tsx` — parses `{{name}}` placeholders out of `text` and renders `<RelativeAnchor iso=... />` children; pure presentational component, no fetch.
- `services/web/src/components/RelativeAnchor.tsx` (co-located inside `CoachText.tsx` is fine if small) — given an ISO timestamp, renders `"10:00 PM (in 47m)"`, updating every 30s.
- `services/web/src/lib/useNow.test.ts`, `services/web/src/components/CoachText.test.tsx` — vitest unit tests.

**Docs — modify:**
- `compose/README.md` (if it exists, else `docs/`) — short note: HA REST command for `POST /coach/ack/kiosk-latest` with `X-API-Key`. *Defer to the final task; see Task 12.*

---

## Task 1: Add `anchors` to the `Insight` dataclass and persistence

**Files:**
- Modify: `services/api/app/services/coach/brief.py` (Insight dataclass at line 193; `save_insight` ~line 420; `recent_insights` ~line 379)
- Test: `services/api/tests/test_coach_anchors.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# services/api/tests/test_coach_anchors.py
from datetime import UTC, datetime

import pytest

from app.services.coach.brief import Insight, recent_insights, save_insight


@pytest.mark.asyncio
async def test_save_and_recent_round_trip_anchors(test_db):
    insight = Insight(
        text="Lights out at {{lights_out}}.",
        model="m",
        eval_ms=0,
        total_ms=0,
        generated_at=datetime.now(UTC),
        context={},
        trigger="manual",
        anchors={"lights_out": "2026-05-19T22:00:00-05:00"},
    )
    insight.id = await save_insight(test_db, insight)
    rows = await recent_insights(test_db, limit=5)
    assert rows[0]["anchors"] == {"lights_out": "2026-05-19T22:00:00-05:00"}
```

The repo conftest exposes a `test_db` async Mongo fixture; mirror the pattern used in `services/api/tests/test_coach.py`.

- [ ] **Step 2: Run test to verify it fails**

Run from `services/api/`:
```bash
.venv/bin/pytest tests/test_coach_anchors.py -v
```
Expected: FAIL — `Insight.__init__()` got an unexpected keyword argument 'anchors' (or AttributeError).

- [ ] **Step 3: Add the field and persist it**

In `services/api/app/services/coach/brief.py`, in the `Insight` dataclass (after `thread_id`):
```python
    anchors: dict[str, str] | None = None
```

In `save_insight`, add to the `doc` dict:
```python
        "anchors": insight.anchors,
```

In `recent_insights`, add to the dict yielded per row:
```python
            "anchors": doc.get("anchors"),
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_coach_anchors.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/coach/brief.py services/api/tests/test_coach_anchors.py
git commit -m "feat(coach): persist anchors field on insights"
```

---

## Task 2: Brief LLM call returns JSON `{text, anchors}` and parses it

**Files:**
- Modify: `services/api/app/services/coach/brief.py` (`generate_insight` ~line 494; `BRIEF_SYSTEM_PROMPT` ~line 140)
- Test: `services/api/tests/test_coach_anchors.py`

The brief currently returns prose. We switch it to JSON output (the kwarg `response_format="json"` already exists, used by kiosk). The model returns `{"text": "...", "anchors": {...}}`. Parse it; fall back to treating the raw response as `text` and `anchors={}` if parsing fails (defensive — kiosk does the same).

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_coach_anchors.py`:
```python
from unittest.mock import patch

@pytest.mark.asyncio
async def test_generate_insight_parses_anchors_from_json(test_db, test_settings):
    fake_resp = {
        "response": '{"text": "Lights out at {{lights_out}}.", "anchors": {"lights_out": "2026-05-19T22:00:00-05:00"}}',
        "eval_duration": 0,
        "total_duration": 0,
    }
    with patch("app.services.coach.brief.httpx.AsyncClient") as mock_client:
        instance = mock_client.return_value.__aenter__.return_value
        instance.post.return_value.json.return_value = fake_resp
        instance.post.return_value.raise_for_status = lambda: None
        from app.services.coach.brief import generate_insight
        insight = await generate_insight(test_settings, test_db, trigger="manual")
    assert insight.text == "Lights out at {{lights_out}}."
    assert insight.anchors == {"lights_out": "2026-05-19T22:00:00-05:00"}


@pytest.mark.asyncio
async def test_generate_insight_falls_back_when_json_invalid(test_db, test_settings):
    fake_resp = {
        "response": "not json at all just prose",
        "eval_duration": 0,
        "total_duration": 0,
    }
    with patch("app.services.coach.brief.httpx.AsyncClient") as mock_client:
        instance = mock_client.return_value.__aenter__.return_value
        instance.post.return_value.json.return_value = fake_resp
        instance.post.return_value.raise_for_status = lambda: None
        from app.services.coach.brief import generate_insight
        insight = await generate_insight(test_settings, test_db, trigger="manual")
    assert insight.text == "not json at all just prose"
    assert insight.anchors == {} or insight.anchors is None
```

Reuse or add a `test_settings` fixture in `conftest.py` if needed; mirror `test_coach.py`.

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_coach_anchors.py::test_generate_insight_parses_anchors_from_json -v
```
Expected: FAIL — `insight.text` is the raw JSON string; `anchors` is None.

- [ ] **Step 3: Parse JSON in `generate_insight`**

In `services/api/app/services/coach/brief.py`, inside `generate_insight`, replace the section that currently builds the `Insight` (lines ~527–539) with:

```python
    raw_text = (data.get("response") or "").strip()
    parsed_text = raw_text
    parsed_anchors: dict[str, str] = {}
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            t = parsed.get("text")
            if isinstance(t, str) and t.strip():
                parsed_text = t.strip()
            a = parsed.get("anchors")
            if isinstance(a, dict):
                parsed_anchors = {
                    str(k): str(v) for k, v in a.items()
                    if isinstance(k, str) and isinstance(v, str)
                }
    except (ValueError, TypeError):
        # Model didn't comply with JSON mode — fall back to raw prose so we
        # never 500 the brief. Anchors stay empty; FE renders plain text.
        pass
    insight = Insight(
        text=parsed_text,
        model=settings.ollama_model,
        eval_ms=int(data.get("eval_duration", 0)) // 1_000_000,
        total_ms=int(data.get("total_duration", 0)) // 1_000_000,
        generated_at=datetime.now(UTC),
        context=findings.to_dict(),
        trigger=trigger,
        food_totals=findings.food_totals,
        history_snapshot=history,
        prompt=prompt,
        system_prompt=system_prompt,
        anchors=parsed_anchors,
    )
```

Then a few lines above, set the request payload to JSON mode by default (kiosk already passes `response_format="json"` explicitly; brief now needs it too). Change the call site to default `response_format="json"`:

Update `generate_insight`'s signature default:
```python
    response_format: str | None = "json",
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_coach_anchors.py -v
```
Expected: PASS for both new tests + the round-trip test from Task 1.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/coach/brief.py services/api/tests/test_coach_anchors.py
git commit -m "feat(coach): brief returns JSON {text, anchors}; defensive fallback"
```

---

## Task 3: Update prompt copy — brief and kiosk learn about anchors

**Files:**
- Modify: `services/api/app/services/coach/brief.py` (`BRIEF_SYSTEM_PROMPT` ~line 140, `KIOSK_SYSTEM_PROMPT` ~line 100)
- Test: `services/api/tests/test_coach_anchors.py`

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_coach_anchors.py`:
```python
from app.services.coach.brief import BRIEF_SYSTEM_PROMPT, KIOSK_SYSTEM_PROMPT


def test_brief_prompt_documents_anchors_contract():
    assert "{{lights_out}}" in BRIEF_SYSTEM_PROMPT or "{{name}}" in BRIEF_SYSTEM_PROMPT
    assert "anchors" in BRIEF_SYSTEM_PROMPT
    # No relative time phrasing instruction should be required by the prompt.
    assert "in N minutes" in BRIEF_SYSTEM_PROMPT or "Never write" in BRIEF_SYSTEM_PROMPT


def test_kiosk_prompt_documents_anchors_field():
    assert "anchors" in KIOSK_SYSTEM_PROMPT
    assert "{{" in KIOSK_SYSTEM_PROMPT  # at least one placeholder example
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_coach_anchors.py -k "prompt" -v
```
Expected: FAIL.

- [ ] **Step 3: Edit the prompts**

In `BRIEF_SYSTEM_PROMPT`, replace the final paragraph (or append a new section before the closing `)`) so the prompt ends with:

```
Output STRICT JSON: { "text": <the brief, 2-4 sentences>, "anchors": { <name>: <ISO-8601 timestamp with timezone offset> } }. No markdown, no preamble.

When you reference a specific time (a deadline, a meal window, a lights-out target, the next workout), do NOT write 'in 47 minutes' or 'in two hours' — those go stale by the time Jim reads them. Instead, use a placeholder like {{lights_out}} inside `text` and add the absolute timestamp under `anchors` with the same name. The browser substitutes it live. Example:

  { "text": "Lights out at {{lights_out}} keeps the streak alive.",
    "anchors": { "lights_out": "2026-05-19T22:00:00-05:00" } }

Never write 'in N minutes' or 'N hours from now'. Always anchor.
```

In `KIOSK_SYSTEM_PROMPT`, extend the JSON schema description so the model knows the 5th field exists. After the `coach` field's section, add:

```
  anchors    — optional dict mapping placeholder name → ISO-8601 timestamp. Use placeholders like {{lights_out}} inside the `coach` field for any specific time reference; never write 'in N minutes'. Example: "coach": "Lights out at {{lights_out}} — 20 minutes left.", "anchors": {"lights_out": "2026-05-19T22:00:00-05:00"}. If no time is referenced, omit or send {}.
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_coach_anchors.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/coach/brief.py services/api/tests/test_coach_anchors.py
git commit -m "feat(coach): prompts instruct model to emit anchors instead of relative time"
```

---

## Task 4: Kiosk router parses `anchors` out of kiosk JSON

**Files:**
- Modify: `services/api/app/routers/coach.py` (`kiosk` handler ~line 91)
- Test: `services/api/tests/test_coach_kiosk.py` (existing) — add a test, or new `test_coach_ack.py`

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_coach_kiosk.py`:
```python
@pytest.mark.asyncio
async def test_kiosk_serializes_anchors_field(client, monkeypatch):
    fake_json = (
        '{"verb": "WIND DOWN", "qualifier": "20 min left", '
        '"urgency": "action", "coach": "Lights out at {{lights_out}}.", '
        '"anchors": {"lights_out": "2026-05-19T22:00:00-05:00"}}'
    )
    # Patch generate_insight to return a stub Insight with this text.
    from app.services.coach.brief import Insight
    from datetime import UTC, datetime
    stub = Insight(
        text=fake_json, model="m", eval_ms=0, total_ms=0,
        generated_at=datetime.now(UTC), context={"attention": ["lights_out"]},
        trigger="kiosk",
    )
    async def fake_gen(*a, **kw):
        return stub
    monkeypatch.setattr("app.routers.coach.generate_insight", fake_gen)
    r = await client.get("/coach/kiosk", headers={"X-API-Key": "test"})
    assert r.status_code == 200
    body = r.json()
    assert body["anchors"] == {"lights_out": "2026-05-19T22:00:00-05:00"}
    assert body["coach"] == "Lights out at {{lights_out}}."
```

Follow the existing fixture pattern from `test_coach_kiosk.py` — the `client` fixture there shows the right shape.

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_coach_kiosk.py::test_kiosk_serializes_anchors_field -v
```
Expected: FAIL — `body` has no `anchors` key.

- [ ] **Step 3: Parse anchors in the kiosk handler**

In `services/api/app/routers/coach.py`, inside the `kiosk` handler's `try: parsed = json.loads(result.text)` block (~line 134), add after the `coach` line:
```python
        anchors = parsed.get("anchors") or {}
        if isinstance(anchors, dict):
            payload["anchors"] = {
                str(k): str(v) for k, v in anchors.items()
                if isinstance(k, str) and isinstance(v, str)
            }
        else:
            payload["anchors"] = {}
```

And in the `except` fallback block, add:
```python
        payload["anchors"] = {}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_coach_kiosk.py -v
```
Expected: PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/routers/coach.py services/api/tests/test_coach_kiosk.py
git commit -m "feat(coach): kiosk endpoint surfaces anchors from JSON output"
```

---

## Task 5: `_serialize` includes `anchors` and `acked_at`; add `acked_at` to recent_insights

**Files:**
- Modify: `services/api/app/routers/coach.py` (`_serialize` ~line 19)
- Modify: `services/api/app/services/coach/brief.py` (`recent_insights` ~line 379, `Insight` dataclass ~line 193, `save_insight` ~line 420)
- Test: `services/api/tests/test_coach_ack.py` (new)

- [ ] **Step 1: Write the failing test**

Create `services/api/tests/test_coach_ack.py`:
```python
from datetime import UTC, datetime

import pytest

from app.services.coach.brief import Insight, recent_insights, save_insight


@pytest.mark.asyncio
async def test_recent_insights_returns_acked_at(test_db):
    insight = Insight(
        text="hello", model="m", eval_ms=0, total_ms=0,
        generated_at=datetime.now(UTC), context={}, trigger="manual",
    )
    insight.id = await save_insight(test_db, insight)
    rows = await recent_insights(test_db, limit=5)
    assert "acked_at" in rows[0]
    assert rows[0]["acked_at"] is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_coach_ack.py -v
```
Expected: FAIL — `acked_at` key missing.

- [ ] **Step 3: Add `acked_at` to Insight + persistence + recent**

In `services/api/app/services/coach/brief.py`:

`Insight` dataclass — add:
```python
    acked_at: datetime | None = None
```

`save_insight` doc dict — add:
```python
        "acked_at": insight.acked_at,
```

`recent_insights` yielded dict — add:
```python
            "acked_at": doc.get("acked_at"),
```

In `services/api/app/routers/coach.py`, in `_serialize`:
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
        "anchors": insight.anchors or {},
        "acked_at": insight.acked_at,
    }
```

- [ ] **Step 4: Run test to verify it passes**

```bash
.venv/bin/pytest tests/test_coach_ack.py tests/test_coach_anchors.py -v
```
Expected: PASS, no regressions.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/coach/brief.py services/api/app/routers/coach.py services/api/tests/test_coach_ack.py
git commit -m "feat(coach): persist acked_at on insights, surface in serializer + recent"
```

---

## Task 6: `POST /coach/insights/{id}/ack` endpoint

**Files:**
- Modify: `services/api/app/routers/coach.py` (add a new route near the existing insight routes ~line 224)
- Test: `services/api/tests/test_coach_ack.py`

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_coach_ack.py`:
```python
@pytest.mark.asyncio
async def test_ack_insight_by_id_sets_acked_at(client, test_db):
    insight = Insight(
        text="hi", model="m", eval_ms=0, total_ms=0,
        generated_at=datetime.now(UTC), context={}, trigger="manual",
    )
    insight.id = await save_insight(test_db, insight)

    r = await client.post(
        f"/coach/insights/{insight.id}/ack",
        headers={"X-API-Key": "test"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == insight.id
    assert body["acked_at"] is not None

    # Idempotent: a second call returns the same acked_at.
    first_acked = body["acked_at"]
    r2 = await client.post(
        f"/coach/insights/{insight.id}/ack",
        headers={"X-API-Key": "test"},
    )
    assert r2.status_code == 200
    assert r2.json()["acked_at"] == first_acked


@pytest.mark.asyncio
async def test_ack_unknown_insight_returns_404(client):
    r = await client.post(
        "/coach/insights/507f1f77bcf86cd799439011/ack",
        headers={"X-API-Key": "test"},
    )
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_coach_ack.py -k "ack_insight_by_id or ack_unknown" -v
```
Expected: FAIL — 404 from FastAPI (route not registered).

- [ ] **Step 3: Implement the endpoint**

In `services/api/app/routers/coach.py`, add after the existing `/insights/{id}/feedback` route (search for it; if absent, anywhere among the other `/insights` routes):
```python
@router.post("/insights/{insight_id}/ack")
async def ack_insight(request: Request, insight_id: str) -> dict[str, Any]:
    db = request.app.state.db
    oid = _oid(insight_id)
    doc = await db["coach_insights"].find_one({"_id": oid})
    if doc is None:
        raise HTTPException(status_code=404, detail="insight not found")
    if doc.get("acked_at") is not None:
        return {"id": insight_id, "acked_at": doc["acked_at"]}
    now = datetime.now(UTC)
    await db["coach_insights"].update_one(
        {"_id": oid}, {"$set": {"acked_at": now}},
    )
    return {"id": insight_id, "acked_at": now}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_coach_ack.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/routers/coach.py services/api/tests/test_coach_ack.py
git commit -m "feat(coach): POST /coach/insights/{id}/ack endpoint, idempotent"
```

---

## Task 7: `POST /coach/ack/web-latest` and `/coach/ack/kiosk-latest`

**Files:**
- Modify: `services/api/app/routers/coach.py`
- Test: `services/api/tests/test_coach_ack.py`

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_coach_ack.py`:
```python
from datetime import timedelta
from app.services.coach.brief import resolve_day_window


@pytest.mark.asyncio
async def test_ack_web_latest_picks_most_recent_manual_today(client, test_db):
    start, end = resolve_day_window(None, None)
    older = Insight(
        text="older", model="m", eval_ms=0, total_ms=0,
        generated_at=start + timedelta(hours=1), context={}, trigger="manual",
    )
    newer = Insight(
        text="newer", model="m", eval_ms=0, total_ms=0,
        generated_at=start + timedelta(hours=5), context={}, trigger="manual",
    )
    kiosk = Insight(
        text="kiosk", model="m", eval_ms=0, total_ms=0,
        generated_at=start + timedelta(hours=6), context={}, trigger="kiosk",
    )
    older.id = await save_insight(test_db, older)
    newer.id = await save_insight(test_db, newer)
    kiosk.id = await save_insight(test_db, kiosk)

    r = await client.post(
        f"/coach/ack/web-latest?start={start.isoformat()}&end={end.isoformat()}",
        headers={"X-API-Key": "test"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == newer.id

    doc_older = await test_db["coach_insights"].find_one({"_id": _oid_helper(older.id)})
    doc_kiosk = await test_db["coach_insights"].find_one({"_id": _oid_helper(kiosk.id)})
    assert doc_older.get("acked_at") is None
    assert doc_kiosk.get("acked_at") is None


@pytest.mark.asyncio
async def test_ack_kiosk_latest_picks_kiosk_only(client, test_db):
    start, end = resolve_day_window(None, None)
    manual = Insight(
        text="manual", model="m", eval_ms=0, total_ms=0,
        generated_at=start + timedelta(hours=2), context={}, trigger="manual",
    )
    kiosk = Insight(
        text="kiosk", model="m", eval_ms=0, total_ms=0,
        generated_at=start + timedelta(hours=3), context={}, trigger="kiosk",
    )
    manual.id = await save_insight(test_db, manual)
    kiosk.id = await save_insight(test_db, kiosk)
    r = await client.post(
        f"/coach/ack/kiosk-latest?start={start.isoformat()}&end={end.isoformat()}",
        headers={"X-API-Key": "test"},
    )
    assert r.status_code == 200
    assert r.json()["id"] == kiosk.id


@pytest.mark.asyncio
async def test_ack_latest_returns_null_when_nothing_eligible(client, test_db):
    r = await client.post(
        "/coach/ack/web-latest",
        headers={"X-API-Key": "test"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body == {"id": None, "acked_at": None}
```

Add a small helper at the top of the test file:
```python
from bson import ObjectId
def _oid_helper(s: str) -> ObjectId:
    return ObjectId(s)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_coach_ack.py -k "latest" -v
```
Expected: FAIL — 404 on the new routes.

- [ ] **Step 3: Implement the endpoints**

In `services/api/app/routers/coach.py`, add (place after the by-id ack route):
```python
async def _ack_latest_for(
    db, trigger: str, day_start: datetime | None, day_end: datetime | None,
) -> dict[str, Any]:
    start, end = resolve_day_window(day_start, day_end)
    doc = await db["coach_insights"].find_one(
        {
            "trigger": trigger,
            "generated_at": {"$gte": start, "$lt": end},
        },
        sort=[("generated_at", -1)],
    )
    if doc is None:
        return {"id": None, "acked_at": None}
    if doc.get("acked_at") is not None:
        return {"id": str(doc["_id"]), "acked_at": doc["acked_at"]}
    now = datetime.now(UTC)
    await db["coach_insights"].update_one(
        {"_id": doc["_id"]}, {"$set": {"acked_at": now}},
    )
    return {"id": str(doc["_id"]), "acked_at": now}


@router.post("/ack/web-latest")
async def ack_web_latest(
    request: Request,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
) -> dict[str, Any]:
    return await _ack_latest_for(request.app.state.db, "manual", start, end)


@router.post("/ack/kiosk-latest")
async def ack_kiosk_latest(
    request: Request,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
) -> dict[str, Any]:
    return await _ack_latest_for(request.app.state.db, "kiosk", start, end)
```

Add the import at the top if missing:
```python
from app.services.coach.brief import resolve_day_window
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_coach_ack.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/routers/coach.py services/api/tests/test_coach_ack.py
git commit -m "feat(coach): POST /coach/ack/{web,kiosk}-latest endpoints scoped by surface"
```

---

## Task 8: History fed into the prompt carries acked flag; kiosk history is surface-scoped

**Files:**
- Modify: `services/api/app/services/coach/brief.py` (`recent_insights` ~line 379, `render_brief_prompt` ~line 446, `generate_insight` ~line 494)
- Test: `services/api/tests/test_coach_ack.py`

Currently `recent_insights(include_kiosk=False)` is what `generate_insight` calls — meaning the brief sees web history, and the kiosk also sees web history (and never its own). We add a third mode: `surface="manual"` or `surface="kiosk"` that filters by trigger.

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_coach_ack.py`:
```python
@pytest.mark.asyncio
async def test_history_marks_acked_and_filters_by_surface(test_db):
    start, end = resolve_day_window(None, None)
    web_acked = Insight(
        text="seen", model="m", eval_ms=0, total_ms=0,
        generated_at=start + timedelta(hours=1), context={}, trigger="manual",
        acked_at=datetime.now(UTC),
    )
    web_fresh = Insight(
        text="new", model="m", eval_ms=0, total_ms=0,
        generated_at=start + timedelta(hours=2), context={}, trigger="manual",
    )
    kiosk_only = Insight(
        text="k", model="m", eval_ms=0, total_ms=0,
        generated_at=start + timedelta(hours=3), context={}, trigger="kiosk",
    )
    for i in (web_acked, web_fresh, kiosk_only):
        i.id = await save_insight(test_db, i)

    rows = await recent_insights(test_db, since=start, surface="manual")
    texts = {r["text"]: r for r in rows}
    assert "k" not in texts
    assert texts["seen"]["acked"] is True
    assert texts["new"]["acked"] is False

    krows = await recent_insights(test_db, since=start, surface="kiosk")
    assert len(krows) == 1
    assert krows[0]["text"] == "k"


def test_render_brief_prompt_flags_acked_messages():
    from app.services.coach.brief import Findings, render_brief_prompt
    history = [
        {"trigger": "manual", "text": "old nudge", "acked": True,
         "generated_at": datetime.now(UTC)},
        {"trigger": "manual", "text": "fresh nudge", "acked": False,
         "generated_at": datetime.now(UTC)},
    ]
    findings = Findings(
        snapshot={}, metrics={}, on_track=[], attention=[],
        food_totals=None, habits=[], day_note=None, coach_note=None,
    )
    prompt = render_brief_prompt(findings, history)
    assert "[acked]" in prompt or "acknowledged" in prompt
    assert "old nudge" in prompt
    assert "fresh nudge" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/pytest tests/test_coach_ack.py -k "history" -v
```
Expected: FAIL — `surface` kwarg unknown; `[acked]` not in prompt.

- [ ] **Step 3: Add `surface` kwarg to `recent_insights` and `acked` flag**

In `services/api/app/services/coach/brief.py`, change `recent_insights`:
```python
async def recent_insights(
    db: AsyncDatabase,
    limit: int = RECENT_LIMIT,
    *,
    since: datetime | None = None,
    include_kiosk: bool = False,
    surface: str | None = None,
) -> list[dict[str, Any]]:
    """...docstring updated..."""
    query: dict[str, Any] = {}
    if since is not None:
        query["generated_at"] = {"$gte": since}
    if surface is not None:
        query["trigger"] = surface
    elif not include_kiosk:
        query["trigger"] = {"$ne": "kiosk"}
    cur = db["coach_insights"].find(query).sort("generated_at", -1).limit(limit)
    return [
        {
            "id": str(doc["_id"]),
            "generated_at": doc.get("generated_at"),
            "text": doc.get("text"),
            "trigger": doc.get("trigger", "manual"),
            "food_totals": doc.get("food_totals"),
            "context": doc.get("context"),
            "anchors": doc.get("anchors"),
            "acked_at": doc.get("acked_at"),
            "acked": doc.get("acked_at") is not None,
        }
        async for doc in cur
    ]
```

In `generate_insight`, change the history call so it scopes to the same surface as the trigger being generated:
```python
    history_surface = "kiosk" if trigger == "kiosk" else "manual"
    history = await recent_insights(db, since=day_start, surface=history_surface)
```

In `render_brief_prompt`, change the history loop to annotate acked items:
```python
    if history:
        parts.append("Recent coach messages (oldest first):")
        for h in reversed(history):
            ts = h.get("generated_at")
            ts_s = (
                ts.isoformat(timespec="minutes")
                if isinstance(ts, datetime) else str(ts)
            )
            tag = "acked" if h.get("acked") else "unacked"
            parts.append(
                f"[{h.get('trigger', 'manual')} @ {ts_s}] [{tag}] {h.get('text', '')}",
            )
        parts.append("")
        parts.append(
            "Items tagged [acked] were explicitly read by Jim — do not "
            "restate them; build on or move past them. Items tagged "
            "[unacked] may be refined if still the most important thing.",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/pytest tests/test_coach_ack.py tests/test_coach.py tests/test_coach_anchors.py -v
```
Expected: PASS. If any pre-existing test breaks because of the surface change (e.g. test expecting kiosk insights in non-kiosk history), inspect and adjust — those tests are likely asserting old behavior we're intentionally tightening.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/coach/brief.py services/api/tests/test_coach_ack.py
git commit -m "feat(coach): surface-scoped history with acked flag; prompt instructs to skip acked items"
```

---

## Task 9: FE — `useNow` hook + `<CoachText>` component

**Files:**
- Create: `services/web/src/lib/useNow.ts`
- Create: `services/web/src/lib/useNow.test.ts`
- Create: `services/web/src/components/CoachText.tsx`
- Create: `services/web/src/components/CoachText.test.tsx`
- Modify: `services/web/src/api/types.ts` (add `anchors?` to CoachInsight/KioskGlance/CoachRecentEntry)

- [ ] **Step 1: Write the failing tests**

Create `services/web/src/lib/useNow.test.ts`:
```typescript
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useNow } from "./useNow";

describe("useNow", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns the current date and updates after the interval", () => {
    vi.setSystemTime(new Date("2026-05-19T10:00:00Z"));
    const { result } = renderHook(() => useNow(30_000));
    const t0 = result.current.getTime();
    act(() => {
      vi.advanceTimersByTime(30_000);
    });
    expect(result.current.getTime()).toBeGreaterThan(t0);
  });
});
```

Create `services/web/src/components/CoachText.test.tsx`:
```tsx
import { render, screen, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CoachText } from "./CoachText";

describe("CoachText", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-19T21:15:00-05:00"));
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders text with a single anchor as 'clock (in Nm)'", () => {
    render(
      <CoachText
        text="Lights out at {{lights_out}} keeps the streak."
        anchors={{ lights_out: "2026-05-19T22:00:00-05:00" }}
      />,
    );
    // 10:00 PM is 45 minutes ahead.
    expect(screen.getByText(/Lights out at/)).toBeInTheDocument();
    expect(screen.getByText(/in 45m/)).toBeInTheDocument();
    expect(screen.getByText(/10:00/)).toBeInTheDocument();
  });

  it("ticks the relative chip after time passes", () => {
    render(
      <CoachText
        text="At {{x}}"
        anchors={{ x: "2026-05-19T22:00:00-05:00" }}
      />,
    );
    expect(screen.getByText(/in 45m/)).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(60_000); });
    expect(screen.getByText(/in 44m/)).toBeInTheDocument();
  });

  it("renders 'Nm ago' when anchor is in the past", () => {
    render(
      <CoachText
        text="Was at {{x}}"
        anchors={{ x: "2026-05-19T21:10:00-05:00" }}
      />,
    );
    expect(screen.getByText(/5m ago/)).toBeInTheDocument();
  });

  it("renders plain text when no anchors provided", () => {
    render(<CoachText text="No times here" anchors={null} />);
    expect(screen.getByText("No times here")).toBeInTheDocument();
  });

  it("leaves unmatched placeholders as literal text", () => {
    render(<CoachText text="Hello {{nope}}" anchors={{}} />);
    expect(screen.getByText(/{{nope}}/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run from `services/web/`:
```bash
npm test -- --run useNow CoachText
```
Expected: FAIL — modules don't exist.

- [ ] **Step 3: Implement `useNow`**

Create `services/web/src/lib/useNow.ts`:
```typescript
import { useEffect, useState } from "react";

/** Returns a Date that re-renders subscribers on an interval.
 *  Default 30s — enough to keep "in Nm" chips honest without burning render. */
export function useNow(intervalMs = 30_000): Date {
  const [now, setNow] = useState<Date>(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
```

- [ ] **Step 4: Implement `CoachText` + `RelativeAnchor`**

Create `services/web/src/components/CoachText.tsx`:
```tsx
import { Fragment } from "react";

import { useNow } from "../lib/useNow";

interface CoachTextProps {
  text: string;
  anchors?: Record<string, string> | null;
}

const PLACEHOLDER_RE = /\{\{([a-zA-Z0-9_]+)\}\}/g;

/** Splits `text` on `{{name}}` placeholders. Each placeholder whose name is in
 *  `anchors` renders as a live <RelativeAnchor>. Unknown names stay literal. */
export function CoachText({ text, anchors }: CoachTextProps) {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  const re = new RegExp(PLACEHOLDER_RE);
  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    const name = match[1];
    const iso = anchors?.[name];
    if (iso) {
      parts.push(<RelativeAnchor key={`${name}-${match.index}`} iso={iso} />);
    } else {
      parts.push(match[0]);
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return (
    <>
      {parts.map((p, i) => (
        <Fragment key={i}>{p}</Fragment>
      ))}
    </>
  );
}

function formatClock(d: Date): string {
  return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function formatRelative(targetMs: number, nowMs: number): string {
  const diffMs = targetMs - nowMs;
  const ahead = diffMs >= 0;
  const absMs = Math.abs(diffMs);
  const mins = Math.round(absMs / 60_000);
  if (mins < 60) return ahead ? `in ${mins}m` : `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  const rem = mins % 60;
  const tail = rem > 0 ? `${hours}h ${rem}m` : `${hours}h`;
  return ahead ? `in ${tail}` : `${tail} ago`;
}

function RelativeAnchor({ iso }: { iso: string }) {
  const now = useNow(30_000);
  const target = new Date(iso);
  if (Number.isNaN(target.getTime())) return <>{iso}</>;
  return (
    <span className="whitespace-nowrap">
      {formatClock(target)} ({formatRelative(target.getTime(), now.getTime())})
    </span>
  );
}
```

- [ ] **Step 5: Add anchors to types**

In `services/web/src/api/types.ts`, modify the existing interfaces:
```typescript
export interface CoachInsight {
  id: string | null;
  text: string;
  model: string;
  eval_ms: number;
  total_ms: number;
  generated_at: string;
  context: Record<string, unknown>;
  trigger: string;
  food_totals?: CoachFoodTotals | null;
  thread_id?: string | null;
  anchors?: Record<string, string> | null;
  acked_at?: string | null;
}

export interface KioskGlance extends CoachInsight {
  verb: string;
  qualifier: string;
  urgency: KioskUrgency;
  coach: string;
}

export interface CoachRecentEntry {
  id: string;
  text: string;
  generated_at: string;
  trigger: string;
  food_totals?: CoachFoodTotals | null;
  context?: Record<string, unknown> | null;
  anchors?: Record<string, string> | null;
  acked_at?: string | null;
}
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
npm test -- --run useNow CoachText
```
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add services/web/src/lib/useNow.ts services/web/src/lib/useNow.test.ts \
        services/web/src/components/CoachText.tsx services/web/src/components/CoachText.test.tsx \
        services/web/src/api/types.ts
git commit -m "feat(web): useNow hook + CoachText component for live anchor rendering"
```

---

## Task 10: FE — client.ts ack methods

**Files:**
- Modify: `services/web/src/api/client.ts`

- [ ] **Step 1: Add the three ack methods**

In `services/web/src/api/client.ts`, near the other coach endpoints (~line 232), add:
```typescript
  coachAck: (insight_id: string) =>
    post<{ id: string; acked_at: string | null }>(
      `/coach/insights/${insight_id}/ack`,
      {},
    ),
  coachAckWebLatest: () => {
    const { start, end } = localDayBoundsUTC(todayLocalISO());
    return post<{ id: string | null; acked_at: string | null }>(
      `/coach/ack/web-latest?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
      {},
    );
  },
  coachAckKioskLatest: () => {
    const { start, end } = localDayBoundsUTC(todayLocalISO());
    return post<{ id: string | null; acked_at: string | null }>(
      `/coach/ack/kiosk-latest?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
      {},
    );
  },
```

Check that `post`, `localDayBoundsUTC`, and `todayLocalISO` are already imported in this file — they should be (used by `coachInsight` / `coachRecent`).

- [ ] **Step 2: Verify build**

```bash
npm run build
```
Expected: success, no TS errors.

- [ ] **Step 3: Commit**

```bash
git add services/web/src/api/client.ts
git commit -m "feat(web): coachAck/coachAckWebLatest/coachAckKioskLatest clients"
```

---

## Task 11: FE — CoachCard renders CoachText and exposes ack button

**Files:**
- Modify: `services/web/src/components/CoachCard.tsx`

The current card renders `display.text` as raw text and `display.id` is already known when a fresh insight is available. We:
- Swap the body's `<div>{display.text}</div>` for `<CoachText text={display.text} anchors={display.anchors} />`.
- Add an "ack" button next to (or replacing — see below) the FeedbackRow when `display.id` is set and `display.acked_at` is null.
- When `display.acked_at` is set, render a small "acknowledged at <time>" footer in lieu of the ack button.

- [ ] **Step 1: Extend DisplayMsg and pickDisplay**

Replace the top of `CoachCard.tsx` (the `DisplayMsg` interface and `pickDisplay`) with:
```tsx
interface DisplayMsg {
  id: string | null;
  text: string;
  meta: string;
  food_totals?: CoachFoodTotals | null;
  anchors?: Record<string, string> | null;
  acked_at?: string | null;
}

function pickDisplay(
  fresh: CoachInsight | undefined,
  latest: CoachRecentEntry | undefined,
): DisplayMsg | null {
  if (fresh) {
    return {
      id: fresh.id,
      text: fresh.text,
      meta: `${fresh.model} · ${(fresh.total_ms / 1000).toFixed(1)}s · ${new Date(fresh.generated_at).toLocaleTimeString()}`,
      food_totals: fresh.food_totals,
      anchors: fresh.anchors ?? null,
      acked_at: fresh.acked_at ?? null,
    };
  }
  if (latest) {
    return {
      id: latest.id,
      text: latest.text,
      meta: `${latest.trigger} · ${new Date(latest.generated_at).toLocaleString()}`,
      food_totals: latest.food_totals,
      anchors: latest.anchors ?? null,
      acked_at: latest.acked_at ?? null,
    };
  }
  return null;
}
```

- [ ] **Step 2: Add the ack button + acknowledged footer**

Add this component near `FeedbackRow`:
```tsx
function AckRow({
  insightId,
  ackedAt,
}: {
  insightId: string;
  ackedAt: string | null;
}) {
  const qc = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => api.coachAck(insightId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["coach.recent"] });
    },
  });
  if (ackedAt) {
    return (
      <div className="text-[11px] text-neutral-500 pt-1">
        acknowledged at {new Date(ackedAt).toLocaleTimeString()}
      </div>
    );
  }
  return (
    <div className="pt-1">
      <button
        type="button"
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending}
        className="text-xs px-3 py-1.5 rounded bg-neutral-800 active:bg-neutral-700 disabled:opacity-50"
        aria-label="acknowledge coach message"
      >
        {mutation.isPending ? "acking…" : "✓ got it"}
      </button>
    </div>
  );
}
```

- [ ] **Step 3: Wire CoachText + AckRow into CoachBody**

Replace `CoachBody` with:
```tsx
import { CoachText } from "./CoachText";

function CoachBody({ display, error }: { display: DisplayMsg | null; error: Error | null }) {
  if (display) {
    return (
      <>
        <div className="text-sm whitespace-pre-wrap leading-relaxed">
          <CoachText text={display.text} anchors={display.anchors} />
        </div>
        <div className="text-[10px] text-neutral-500">{display.meta}</div>
        <ModelInputs food_totals={display.food_totals} />
        {display.id && <AckRow insightId={display.id} ackedAt={display.acked_at ?? null} />}
        {display.id && <FeedbackRow key={display.id} insightId={display.id} />}
      </>
    );
  }
  if (error) {
    return <div className="text-sm text-red-400">{error.message}</div>;
  }
  return (
    <div className="text-sm text-neutral-500">
      tap "ask coach" for a quick read on your last 24 hours.
    </div>
  );
}
```

- [ ] **Step 4: Build + smoke check**

```bash
cd services/web && npm run build && npm test -- --run
```
Expected: build succeeds; existing tests still pass.

Manually verify in dev: `npm run dev`, click "ask coach", confirm a live "in Nm" chip ticks (if the LLM emits an anchor), and that the ack button hides + acknowledged footer appears after click.

- [ ] **Step 5: Commit**

```bash
git add services/web/src/components/CoachCard.tsx
git commit -m "feat(web): CoachCard renders anchors live and exposes ack button"
```

---

## Task 12: FE/kiosk — KioskCoachLine uses CoachText and gains ack button

**Files:**
- Modify: `services/web/src/components/kiosk/KioskCoachLine.tsx`

- [ ] **Step 1: Replace the line and add the button**

Replace the contents of `services/web/src/components/kiosk/KioskCoachLine.tsx` with:
```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api/client";
import { CoachText } from "../CoachText";

function fallbackLine(): string {
  return "Coach offline.";
}

export function KioskCoachLine() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["coach-kiosk"],
    queryFn: api.coachKiosk,
    refetchInterval: 5 * 60_000,
    retry: 1,
  });

  const coach = q.data?.coach?.trim() ?? "";
  const text = coach.length > 0 ? coach : fallbackLine();
  const anchors = q.data?.anchors ?? null;
  const ackedAt = q.data?.acked_at ?? null;

  const ack = useMutation({
    mutationFn: api.coachAckKioskLatest,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["coach-kiosk"] });
    },
  });

  return (
    <section className="text-[5rem] font-normal leading-tight text-neutral-100 space-y-6">
      <div>
        <CoachText text={text} anchors={anchors} />
      </div>
      {coach.length > 0 && (
        ackedAt ? (
          <div className="text-2xl text-neutral-500">
            ✓ acknowledged at {new Date(ackedAt).toLocaleTimeString()}
          </div>
        ) : (
          <button
            type="button"
            onClick={() => ack.mutate()}
            disabled={ack.isPending}
            className="text-3xl px-6 py-4 rounded-2xl bg-neutral-800 active:bg-neutral-700 disabled:opacity-50 text-neutral-100"
            aria-label="acknowledge"
          >
            {ack.isPending ? "acking…" : "✓ got it"}
          </button>
        )
      )}
    </section>
  );
}
```

The kiosk JSON payload's `acked_at` field will be `null` for a freshly generated kiosk insight (the cache TTL is 15min — see `_KIOSK_CACHE_TTL` in `routers/coach.py`). Note that since the kiosk handler caches the payload, an ack may not show up in the kiosk UI immediately even after the mutation invalidates the query — the next *server* generation after cache expiry refreshes `acked_at`.

To make the kiosk feel responsive, after a successful ack we also clear the local-cache entry by invalidating; but the server cache outlives that. Accept this for now and address only if it feels broken in dogfood.

- [ ] **Step 2: Build + test**

```bash
cd services/web && npm run build && npm test -- --run
```
Expected: success.

- [ ] **Step 3: Commit**

```bash
git add services/web/src/components/kiosk/KioskCoachLine.tsx
git commit -m "feat(kiosk): live anchor rendering + ack button"
```

---

## Task 13: Kiosk server cache invalidates on ack so the screen reflects it within seconds

**Files:**
- Modify: `services/api/app/routers/coach.py` (`ack_kiosk_latest` and possibly `ack_insight`)

The kiosk handler caches generated payloads on `request.app.state.kiosk_cache` for 15 minutes. When the user (or HA) acks, we want the next `GET /coach/kiosk` to return a payload whose `acked_at` is populated — but the cached payload still has `acked_at: null`. Solution: when the kiosk ack endpoint succeeds, clear `app.state.kiosk_cache`.

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_coach_ack.py`:
```python
@pytest.mark.asyncio
async def test_ack_kiosk_latest_clears_kiosk_cache(client, test_db, app):
    # Seed a fake cache entry.
    app.state.kiosk_cache = {"|": {"stored_at": datetime.now(UTC), "payload": {}}}
    start, end = resolve_day_window(None, None)
    kiosk = Insight(
        text="k", model="m", eval_ms=0, total_ms=0,
        generated_at=start + timedelta(hours=1), context={}, trigger="kiosk",
    )
    kiosk.id = await save_insight(test_db, kiosk)
    r = await client.post(
        f"/coach/ack/kiosk-latest?start={start.isoformat()}&end={end.isoformat()}",
        headers={"X-API-Key": "test"},
    )
    assert r.status_code == 200
    assert app.state.kiosk_cache == {}
```

If the test fixture doesn't expose `app` directly, add a fixture alias in `conftest.py` (mirror `client`). If too messy, drop this test and rely on dogfood — but try first.

- [ ] **Step 2: Run test to verify it fails**

```bash
.venv/bin/pytest tests/test_coach_ack.py::test_ack_kiosk_latest_clears_kiosk_cache -v
```
Expected: FAIL — cache still populated.

- [ ] **Step 3: Clear cache in `ack_kiosk_latest`**

In `services/api/app/routers/coach.py`, modify the `ack_kiosk_latest` handler:
```python
@router.post("/ack/kiosk-latest")
async def ack_kiosk_latest(
    request: Request,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
) -> dict[str, Any]:
    result = await _ack_latest_for(request.app.state.db, "kiosk", start, end)
    # Bust the kiosk cache so the next GET /coach/kiosk reflects the ack
    # instead of returning the 15-min-stale payload with acked_at=null.
    cache = getattr(request.app.state, "kiosk_cache", None)
    if cache is not None:
        cache.clear()
    return result
```

Also extend `ack_insight` to clear the kiosk cache *only if the acked insight is a kiosk insight*:
```python
@router.post("/insights/{insight_id}/ack")
async def ack_insight(request: Request, insight_id: str) -> dict[str, Any]:
    db = request.app.state.db
    oid = _oid(insight_id)
    doc = await db["coach_insights"].find_one({"_id": oid})
    if doc is None:
        raise HTTPException(status_code=404, detail="insight not found")
    if doc.get("acked_at") is not None:
        return {"id": insight_id, "acked_at": doc["acked_at"]}
    now = datetime.now(UTC)
    await db["coach_insights"].update_one(
        {"_id": oid}, {"$set": {"acked_at": now}},
    )
    if doc.get("trigger") == "kiosk":
        cache = getattr(request.app.state, "kiosk_cache", None)
        if cache is not None:
            cache.clear()
    return {"id": insight_id, "acked_at": now}
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_coach_ack.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/routers/coach.py services/api/tests/test_coach_ack.py
git commit -m "fix(coach): bust kiosk cache on ack so screen reflects acknowledged state"
```

---

## Task 14: Full test suite + lint/typecheck pass and final commit

- [ ] **Step 1: Run full backend test suite**

```bash
cd services/api && .venv/bin/pytest -q
```
Expected: PASS.

- [ ] **Step 2: Run full frontend test suite**

```bash
cd services/web && npm test -- --run
```
Expected: PASS.

- [ ] **Step 3: Run lint + typecheck**

If the repo has lint commands wired up (check `services/api/pyproject.toml` for `ruff`/`mypy` recipes and `services/web/package.json` for `lint`/`typecheck`):
```bash
cd services/api && .venv/bin/ruff check . && .venv/bin/mypy app
cd services/web && npm run lint && npm run typecheck 2>/dev/null || tsc --noEmit
```
Expected: clean.

- [ ] **Step 4: Push**

Per the project's CLAUDE.md ("when tests + lint + typecheck are all green, commit and push to master without waiting for explicit approval"):
```bash
git push origin master
```

CI will build the new API image; Watchtower will pull and restart.

- [ ] **Step 5: Smoke-check on `hd` after deploy**

```bash
ssh hd 'docker logs --tail 50 hack-the-body-app 2>&1 | tail -20'
curl -sS -H "X-API-Key: $API_KEY" http://hd:8080/coach/insight | jq .anchors
curl -sS -H "X-API-Key: $API_KEY" -X POST http://hd:8080/coach/ack/kiosk-latest | jq .
```
Expected: anchors object present (may be empty `{}`); kiosk ack endpoint returns `{id, acked_at}`.

If HA configuration is needed, add a one-paragraph note to `docs/coach-debugging.md` (or `compose/README.md` if it exists) documenting the curl shape — but skip writing new docs files unless asked.

---

## Self-Review Notes

- **Spec coverage:** Anchors persisted (T1), brief emits anchors (T2), prompts instruct (T3), kiosk surfaces anchors (T4), ack persisted + serialized (T5), id-ack endpoint (T6), web/kiosk-latest endpoints (T7), surface-scoped history + acked flag in prompt (T8), FE live-rendering (T9–10), FE web ack (T11), FE kiosk ack (T12), cache invalidation (T13), final verification (T14). All spec requirements covered.
- **Open question in spec ("does recent_insights filter by trigger?"):** Resolved in T8 by adding the `surface` kwarg.
- **No placeholders, no TBDs.** Code blocks complete in every code step.
- **Types consistent:** `anchors` is `dict[str, str] | None` server-side and `Record<string, string> | null` client-side; `acked_at` is `datetime | None` / `string | null`. The new `recent_insights` rows expose `acked: bool` (derived) in addition to `acked_at` (raw) — used differently by the prompt renderer (boolean tag) and the FE (display).
