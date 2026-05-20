# Unify Day-Phase into the Coach — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Single source of truth for "when is lights out." Server derives `phase` / `lights_out_at` / `wind_down_mode` from a configurable `lights_out_local`, surfaces them on the coach payload, the coach can reference `{{lights_out}}` via the existing anchor system, and the FE deletes `dayPhase.ts` + `KioskPhaseCard` and reads phase from the response instead.

**Architecture:** Add `lights_out_local: "HH:MM"` to `user_profile.targets`. A new `services/api/app/services/coach/phase.py` exports `compute_phase(now_local, lights_out_local)` returning `{phase, lights_out_at, wind_down_mode}`. The brief + kiosk endpoints embed those fields on the response. The coach prompt's context block gains a `phase` blob so the LLM can reason about wind-down and emit a `{{lights_out}}` anchor. The bedtime habit cutoff reads from the same config. The kiosk FE deletes `dayPhase.ts` + `KioskPhaseCard`, reads `wind_down_mode` from the kiosk response, drops the hide-coach-during-wind-down behavior.

**Tech Stack:** FastAPI + Mongo, React + TanStack Query + Vite, pytest, vitest.

---

## File Structure

**Backend — create:**
- `services/api/app/services/coach/phase.py` — `WIND_DOWN_LEAD_MIN`, `PhaseInfo` dataclass, `compute_phase`.
- `services/api/tests/test_coach_phase.py`

**Backend — modify:**
- `services/api/app/routers/profile.py` — `Targets` model + `_serialize` add `lights_out_local`.
- `services/api/app/services/coach/brief.py` — `gather_context` adds `phase` block sourced from `compute_phase`; both system prompts gain a short paragraph instructing the model to use `{{lights_out}}` during wind-down and acknowledge late hours without nagging.
- `services/api/app/routers/coach.py` — `_serialize` adds `phase`, `lights_out_at`, `wind_down_mode` derived from the request's day window + targets; kiosk handler propagates them onto the cached payload.
- `services/api/app/services/coach/habits.py` — bedtime habit reads `lights_out_local` from targets, replacing `BED_CUTOFF_HOUR`.

**Frontend — delete:**
- `services/web/src/lib/dayPhase.ts`
- `services/web/src/lib/dayPhase.test.ts`
- `services/web/src/components/kiosk/KioskPhaseCard.tsx`

**Frontend — modify:**
- `services/web/src/api/types.ts` — `CoachInsight` / `KioskGlance` gain optional `phase`, `lights_out_at`, `wind_down_mode`.
- `services/web/src/pages/Kiosk.tsx` — `windDownMode` reads from coach-kiosk query; coach line shows always.
- `services/web/src/components/kiosk/KioskHero.tsx` — `urgency === "clear"` no longer returns `<KioskPhaseCard />`. Render an empty/blank hero (no giant text) so the coach line carries the screen.

---

## Task 1: `compute_phase` helper + tests

**Files:**
- Create: `services/api/app/services/coach/phase.py`
- Test: `services/api/tests/test_coach_phase.py`

- [ ] **Step 1: Write the failing tests**

```python
# services/api/tests/test_coach_phase.py
from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.coach.phase import WIND_DOWN_LEAD_MIN, compute_phase


CT = ZoneInfo("America/Chicago")


def test_phase_day_when_far_from_lights_out():
    now = datetime(2026, 5, 19, 14, 0, tzinfo=CT)  # 2 PM
    info = compute_phase(now, "22:00")
    assert info.phase == "day"
    assert info.wind_down_mode is False
    assert info.lights_out_at == datetime(2026, 5, 19, 22, 0, tzinfo=CT)


def test_phase_wind_down_within_lead():
    now = datetime(2026, 5, 19, 21, 0, tzinfo=CT)  # 9 PM, 60 min ahead of 22:00
    info = compute_phase(now, "22:00")
    assert info.phase == "wind-down"
    assert info.wind_down_mode is True


def test_phase_late_after_lights_out():
    now = datetime(2026, 5, 19, 23, 30, tzinfo=CT)
    info = compute_phase(now, "22:00")
    assert info.phase == "late"
    assert info.wind_down_mode is True
    # lights_out_at rolls to tomorrow once we're past today's.
    assert info.lights_out_at == datetime(2026, 5, 20, 22, 0, tzinfo=CT)


def test_phase_late_overnight_before_morning():
    now = datetime(2026, 5, 20, 2, 0, tzinfo=CT)
    info = compute_phase(now, "22:00")
    assert info.phase == "late"


def test_phase_day_back_after_morning():
    now = datetime(2026, 5, 20, 8, 0, tzinfo=CT)
    info = compute_phase(now, "22:00")
    assert info.phase == "day"


def test_phase_wind_down_respects_lead_minutes():
    lights_out = "22:00"
    boundary = datetime(2026, 5, 19, 22, 0, tzinfo=CT)
    just_before = boundary.replace(hour=22 - 1, minute=60 - WIND_DOWN_LEAD_MIN)
    # ^^ that's silly arithmetic — just use the actual boundary minus lead.
    from datetime import timedelta
    just_inside = boundary - timedelta(minutes=WIND_DOWN_LEAD_MIN - 1)
    just_outside = boundary - timedelta(minutes=WIND_DOWN_LEAD_MIN + 1)
    assert compute_phase(just_inside, lights_out).phase == "wind-down"
    assert compute_phase(just_outside, lights_out).phase == "day"


def test_phase_handles_non_default_lights_out():
    now = datetime(2026, 5, 19, 22, 30, tzinfo=CT)
    info = compute_phase(now, "23:30")
    assert info.phase == "wind-down"
    assert info.lights_out_at == datetime(2026, 5, 19, 23, 30, tzinfo=CT)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd services/api && .venv/bin/pytest tests/test_coach_phase.py -v
```
Expected: FAIL (module does not exist).

- [ ] **Step 3: Implement**

Create `services/api/app/services/coach/phase.py`:
```python
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Literal

WIND_DOWN_LEAD_MIN = 90

Phase = Literal["day", "wind-down", "late"]


@dataclass
class PhaseInfo:
    phase: Phase
    lights_out_at: datetime
    wind_down_mode: bool


def _parse_hhmm(s: str) -> time:
    h, m = s.split(":", 1)
    return time(int(h), int(m))


def compute_phase(now_local: datetime, lights_out_local: str) -> PhaseInfo:
    """Derive the day-phase from a tz-aware `now` and an "HH:MM" lights-out.

    `lights_out_at` is the upcoming lights-out: today's if it's still
    ahead, tomorrow's otherwise. "Late" runs from today's lights-out
    until the following morning at 04:00 local; after that we return to
    "day" — the small four-hour buffer keeps middle-of-the-night briefs
    framed as `late` rather than reading as a fresh morning.
    """
    if now_local.tzinfo is None:
        raise ValueError("now_local must be timezone-aware")
    target = _parse_hhmm(lights_out_local)
    todays_lights_out = now_local.replace(
        hour=target.hour, minute=target.minute,
        second=0, microsecond=0,
    )
    morning_break = now_local.replace(
        hour=4, minute=0, second=0, microsecond=0,
    )
    if now_local >= todays_lights_out:
        # Past today's lights-out → late, and next lights-out is tomorrow's.
        return PhaseInfo(
            phase="late",
            lights_out_at=todays_lights_out + timedelta(days=1),
            wind_down_mode=True,
        )
    if now_local < morning_break:
        # Wee hours: still "late" relative to yesterday's lights-out.
        return PhaseInfo(
            phase="late",
            lights_out_at=todays_lights_out,
            wind_down_mode=True,
        )
    delta = todays_lights_out - now_local
    if delta <= timedelta(minutes=WIND_DOWN_LEAD_MIN):
        return PhaseInfo(
            phase="wind-down",
            lights_out_at=todays_lights_out,
            wind_down_mode=True,
        )
    return PhaseInfo(
        phase="day",
        lights_out_at=todays_lights_out,
        wind_down_mode=False,
    )
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_coach_phase.py -v
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/coach/phase.py services/api/tests/test_coach_phase.py
git commit -m "feat(coach): compute_phase helper (day/wind-down/late + lights_out_at)"
```

---

## Task 2: Add `lights_out_local` to `Targets`

**Files:**
- Modify: `services/api/app/routers/profile.py`
- Test: `services/api/tests/test_profile.py`

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_profile.py` (or a new test if patterns dictate — match what's there):

```python
@pytest.mark.asyncio
async def test_targets_round_trip_lights_out_local(client):
    r = await client.put(
        "/profile/targets",
        json={"lights_out_local": "22:30"},
        headers={"X-API-Key": "test-key"},
    )
    assert r.status_code == 200
    assert r.json()["lights_out_local"] == "22:30"

    g = await client.get(
        "/profile/targets",
        headers={"X-API-Key": "test-key"},
    )
    assert g.json()["lights_out_local"] == "22:30"


def test_targets_lights_out_local_validates_format(client):
    # An obviously invalid string should 422.
    import asyncio
    r = asyncio.get_event_loop().run_until_complete(client.put(
        "/profile/targets",
        json={"lights_out_local": "not a time"},
        headers={"X-API-Key": "test-key"},
    ))
    assert r.status_code == 422
```

(Use the existing async test style — mirror nearby tests in the file.)

- [ ] **Step 2: Run tests**

```bash
.venv/bin/pytest tests/test_profile.py -k lights_out -v
```
Expected: FAIL.

- [ ] **Step 3: Implement**

In `services/api/app/routers/profile.py`:

Add to imports:
```python
import re
```

Add a module-level pattern:
```python
_HHMM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
```

Add to the `Targets` class:
```python
    lights_out_local: str | None = Field(
        default=None,
        description=(
            "Local-time lights-out target, 'HH:MM'. Drives the coach's "
            "wind-down phase and the bedtime habit cutoff. None = use "
            "22:00 default."
        ),
    )

    @field_validator("lights_out_local")
    @classmethod
    def _check_hhmm(cls, v: str | None) -> str | None:
        if v is not None and not _HHMM_RE.match(v):
            raise ValueError("must be HH:MM (24h)")
        return v
```

Add `field_validator` to the imports from pydantic:
```python
from pydantic import BaseModel, Field, field_validator
```

Update `_serialize` to include the field:
```python
        "lights_out_local": doc.get("lights_out_local"),
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_profile.py -q
```
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add services/api/app/routers/profile.py services/api/tests/test_profile.py
git commit -m "feat(profile): lights_out_local target (HH:MM, drives phase)"
```

---

## Task 3: Bedtime habit cutoff reads `lights_out_local`

**Files:**
- Modify: `services/api/app/services/coach/habits.py`
- Test: `services/api/tests/test_habits.py`

- [ ] **Step 1: Find and read the bedtime habit logic**

In `services/api/app/services/coach/habits.py`, locate `BED_CUTOFF_HOUR` (line 180) and the `_bedtime_done_check` (or similarly named) function around line 200–215. Read enough context to understand its signature.

- [ ] **Step 2: Write the failing test**

Append to `services/api/tests/test_habits.py` (match the file's existing pattern):

```python
@pytest.mark.asyncio
async def test_bedtime_habit_cutoff_uses_lights_out_local(mock_db):
    # Set a non-default cutoff and verify the bedtime check honors it.
    await mock_db["user_profile"].update_one(
        {"_id": "targets"},
        {"$set": {"lights_out_local": "23:00"}},
        upsert=True,
    )
    # ... call the bedtime done-check with a sleep onset at 22:45 and
    # assert it's marked done (would have been "missed" under the old
    # 22:00 cutoff). Adjust to match the actual function name / shape
    # discovered in step 1.
```

If the existing bedtime test already exercises the cutoff path, replace its hardcoded expectation with a `lights_out_local`-driven one; otherwise add a new test.

- [ ] **Step 3: Run test**

Expected: FAIL.

- [ ] **Step 4: Implement**

Delete `BED_CUTOFF_HOUR`. Update the bedtime check to load `lights_out_local` from `db["user_profile"].find_one({"_id": "targets"})`, default to `"22:00"` when missing, parse via `_parse_hhmm` (import from `phase.py`).

- [ ] **Step 5: Run tests**

```bash
.venv/bin/pytest tests/test_habits.py -q
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add services/api/app/services/coach/habits.py services/api/tests/test_habits.py
git commit -m "feat(habits): bedtime cutoff reads lights_out_local from targets"
```

---

## Task 4: Brief + kiosk responses include phase fields

**Files:**
- Modify: `services/api/app/routers/coach.py` (`_serialize`, `insight` and `kiosk` handlers)
- Modify: `services/api/app/services/coach/brief.py` (`gather_context`)
- Test: `services/api/tests/test_coach.py` and `services/api/tests/test_coach_kiosk.py`

- [ ] **Step 1: Write the failing test (kiosk)**

Append to `services/api/tests/test_coach_kiosk.py`:

```python
@pytest.mark.asyncio
async def test_kiosk_includes_phase_fields(client, mock_db, monkeypatch):
    from datetime import UTC, datetime  # noqa: PLC0415
    from app.services.coach.brief import Insight  # noqa: PLC0415

    stub = Insight(
        text='{"verb":"CLEAR","qualifier":"","urgency":"clear","coach":"hi","anchors":{}}',
        model="m", eval_ms=0, total_ms=0,
        generated_at=datetime.now(UTC), context={"attention": []},
        trigger="kiosk",
    )

    async def fake_gen(*_a, **_kw):
        return stub

    monkeypatch.setattr("app.routers.coach.generate_insight", fake_gen)
    r = await client.get("/coach/kiosk", headers={"X-API-Key": "test-key"})
    assert r.status_code == 200
    body = r.json()
    assert "phase" in body
    assert body["phase"] in ("day", "wind-down", "late")
    assert "lights_out_at" in body
    assert "wind_down_mode" in body
    assert isinstance(body["wind_down_mode"], bool)
```

Append similar test to `services/api/tests/test_coach.py` for `/coach/insight`.

- [ ] **Step 2: Run tests**

Expected: FAIL — fields missing.

- [ ] **Step 3: Implement**

In `services/api/app/routers/coach.py`:

- Add helpers near the top of the file (after imports):

```python
from app.services.coach.phase import compute_phase

async def _phase_for_window(
    db, day_start: datetime | None, day_end: datetime | None,
) -> dict[str, Any]:
    from app.services.coach.brief import resolve_day_window  # noqa: PLC0415
    start, _end = resolve_day_window(day_start, day_end)
    tz_name = os.environ.get("TZ") or "UTC"
    try:
        tz = ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        tz = UTC
    targets_doc = await db["user_profile"].find_one({"_id": "targets"}) or {}
    lights_out_local = targets_doc.get("lights_out_local") or "22:00"
    now_local = datetime.now(UTC).astimezone(tz)
    info = compute_phase(now_local, lights_out_local)
    return {
        "phase": info.phase,
        "lights_out_at": info.lights_out_at.isoformat(),
        "wind_down_mode": info.wind_down_mode,
    }
```

Add `import os` and `from zoneinfo import ZoneInfo, ZoneInfoNotFoundError` if not present.

- Modify both `insight` and `kiosk` handlers to compute the phase block and merge it into the returned payload before returning:

```python
    payload = _serialize(result)
    payload.update(await _phase_for_window(db, start, end))
    # kiosk-specific JSON-parse block stays as-is, after this merge
    return payload
```

For the kiosk handler, the cache should still cache the payload INCLUDING the phase fields — but `phase` is time-sensitive, so do **not** cache it. Easiest fix: cache the LLM payload as today, but compute phase fresh on every request and merge after cache lookup:

```python
    cached = cache.get(key)
    if cached and (now - cached["stored_at"]) < _KIOSK_CACHE_TTL:
        payload = dict(cached["payload"])
        payload.update(await _phase_for_window(db, start, end))
        return payload
    # ... existing generation path ...
    payload = _serialize(result)
    # ... existing kiosk JSON parsing ...
    cache[key] = {"stored_at": now, "payload": payload}
    payload = dict(payload)
    payload.update(await _phase_for_window(db, start, end))
    return payload
```

In `services/api/app/services/coach/brief.py::gather_context`, add the phase block to the `out` dict:

```python
    targets_doc = await ... (already loaded by caller — actually targets is passed in via the targets kwarg). Skip loading here; instead let the caller compute phase and add it. But for `gather_context`, the simplest path: compute phase here too using `targets.get("lights_out_local")` if `targets` is not None, default "22:00".

    lights_out_local = (targets or {}).get("lights_out_local") or "22:00"
    info_phase = compute_phase(now_local := day_start.astimezone(local_tz) + timedelta(seconds=local_seconds), lights_out_local)
    # ^ messy — pick the cleanest local-now we can compute here. Or
    # accept that gather_context recomputes its own local_now.

    out["phase"] = {
        "phase": info_phase.phase,
        "lights_out_at": info_phase.lights_out_at.isoformat(),
        "wind_down_mode": info_phase.wind_down_mode,
    }
```

Computing `now_local` cleanly inside `gather_context`: the function already has `local_tz` and computes `local_hour` / `local_minute`. Build `now_local = datetime.now(UTC).astimezone(local_tz)` once and reuse it. Refactor as needed.

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_coach.py tests/test_coach_kiosk.py tests/test_coach_phase.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/routers/coach.py services/api/app/services/coach/brief.py services/api/tests/test_coach.py services/api/tests/test_coach_kiosk.py
git commit -m "feat(coach): brief + kiosk responses include phase/lights_out_at/wind_down_mode"
```

---

## Task 5: Coach prompt knows about phase

**Files:**
- Modify: `services/api/app/services/coach/brief.py` (`BRIEF_SYSTEM_PROMPT`, `KIOSK_SYSTEM_PROMPT`)
- Test: `services/api/tests/test_coach_anchors.py` (extend existing prompt-shape tests)

- [ ] **Step 1: Write the failing test**

Append to `services/api/tests/test_coach_anchors.py`:

```python
def test_brief_prompt_mentions_phase_and_lights_out_anchor():
    assert "phase" in BRIEF_SYSTEM_PROMPT
    assert "wind-down" in BRIEF_SYSTEM_PROMPT or "wind_down" in BRIEF_SYSTEM_PROMPT
    assert "{{lights_out}}" in BRIEF_SYSTEM_PROMPT


def test_kiosk_prompt_mentions_phase():
    assert "phase" in KIOSK_SYSTEM_PROMPT
    assert "wind-down" in KIOSK_SYSTEM_PROMPT or "wind_down" in KIOSK_SYSTEM_PROMPT
```

- [ ] **Step 2: Run tests**

Expected: FAIL.

- [ ] **Step 3: Implement**

Append to `BRIEF_SYSTEM_PROMPT` (before the closing parenthesis):

```
+ "\n"
+ "\n"
+ "Context includes a `phase` field: `day`, `wind-down`, or `late`. "
+ "During `wind-down`, surface the lights-out anchor with the "
+ "{{lights_out}} placeholder when it's useful — e.g. \"Lights out "
+ "at {{lights_out}} keeps the streak.\" During `late`, acknowledge "
+ "the hour without nagging; do not propose new actions."
```

Append to `KIOSK_SYSTEM_PROMPT`:

```
+ "\n"
+ "\n"
+ "Context includes `phase` (day | wind-down | late). During "
+ "wind-down, the coach sentence may anchor on {{lights_out}}. "
+ "During `late`, prefer CLEAR with a quiet acknowledging coach "
+ "sentence — no action prompt."
```

- [ ] **Step 4: Run tests**

```bash
.venv/bin/pytest tests/test_coach_anchors.py -q
```
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add services/api/app/services/coach/brief.py services/api/tests/test_coach_anchors.py
git commit -m "feat(coach): prompts know about phase + lights_out anchor"
```

---

## Task 6: FE — types + delete dayPhase + update Kiosk

**Files:**
- Modify: `services/web/src/api/types.ts`
- Delete: `services/web/src/lib/dayPhase.ts`, `services/web/src/lib/dayPhase.test.ts`, `services/web/src/components/kiosk/KioskPhaseCard.tsx`
- Modify: `services/web/src/pages/Kiosk.tsx`, `services/web/src/components/kiosk/KioskHero.tsx`

- [ ] **Step 1: Extend types**

In `services/web/src/api/types.ts`, add to `CoachInsight`:
```typescript
  phase?: "day" | "wind-down" | "late";
  lights_out_at?: string;
  wind_down_mode?: boolean;
```

`KioskGlance` inherits these via `extends CoachInsight`.

- [ ] **Step 2: Delete dayPhase files**

```bash
git rm services/web/src/lib/dayPhase.ts services/web/src/lib/dayPhase.test.ts services/web/src/components/kiosk/KioskPhaseCard.tsx
```

- [ ] **Step 3: Rewrite `Kiosk.tsx`**

```tsx
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { KioskCoachLine } from "../components/kiosk/KioskCoachLine";
import { KioskHero } from "../components/kiosk/KioskHero";
import { KioskOpenList } from "../components/kiosk/KioskOpenList";
import { KioskRecoverySentence } from "../components/kiosk/KioskRecoverySentence";
import { KioskTagline } from "../components/kiosk/KioskTagline";
import { KioskTopBar } from "../components/kiosk/KioskTopBar";

export function Kiosk() {
  const q = useQuery({
    queryKey: ["coach-kiosk"],
    queryFn: api.coachKiosk,
    refetchInterval: 5 * 60_000,
    retry: 1,
  });
  const windDownMode = q.data?.wind_down_mode ?? false;

  const wrapperClass = windDownMode
    ? "min-h-screen bg-black p-12 flex flex-col gap-16 font-sans text-amber-100/70 brightness-50"
    : "min-h-screen bg-black text-white p-12 flex flex-col gap-16 font-sans";

  return (
    <div className={wrapperClass}>
      <KioskTopBar />
      <KioskHero />
      <KioskCoachLine />
      {!windDownMode && <KioskOpenList />}
      <div className="flex-1" />
      <KioskRecoverySentence />
      <KioskTagline />
    </div>
  );
}
```

(`KioskCoachLine` and `KioskHero` both already share the `["coach-kiosk"]` query key in TanStack, so adding another one in `Kiosk.tsx` just shares the cached payload.)

- [ ] **Step 4: Rewrite `KioskHero.tsx`**

```tsx
import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";
import type { KioskUrgency } from "../../api/types";

const URGENCY_COLOR: Record<KioskUrgency, string> = {
  clear:   "text-emerald-400",
  action:  "text-amber-400",
  urgent:  "text-red-500",
};

export function KioskHero() {
  const q = useQuery({
    queryKey: ["coach-kiosk"],
    queryFn: api.coachKiosk,
    refetchInterval: 5 * 60_000,
    retry: 1,
  });

  const verb = q.data?.verb?.trim() ?? "";
  const qualifier = q.data?.qualifier?.trim() ?? "";
  const urgency: KioskUrgency = q.data?.urgency ?? "clear";

  if (urgency === "clear") {
    // No action prompt — leave the hero quiet; the coach line carries the screen.
    return <section className="leading-none" />;
  }

  const displayVerb = verb.length > 0 ? verb : "CLEAR";
  const colorClass = URGENCY_COLOR[urgency];

  return (
    <section className="flex flex-col gap-4 leading-none">
      <div className={`text-[14rem] font-semibold tracking-tight ${colorClass}`}>
        {displayVerb}
      </div>
      {qualifier && (
        <div className={`text-[5rem] font-normal ${colorClass} opacity-80`}>
          {qualifier}
        </div>
      )}
    </section>
  );
}
```

- [ ] **Step 5: Build + test**

```bash
cd services/web && npm test -- --run && npm run build
```

If anything else imports `dayPhase` or `KioskPhaseCard`, the typecheck will surface it; fix those imports too.

- [ ] **Step 6: Commit**

```bash
git add services/web/src/api/types.ts services/web/src/pages/Kiosk.tsx services/web/src/components/kiosk/KioskHero.tsx
git commit -m "refactor(kiosk): drop dayPhase + KioskPhaseCard; phase comes from coach response"
```

---

## Task 7: Final verification + push

- [ ] **Step 1: Full backend test**

```bash
cd services/api && .venv/bin/pytest -q
```

The pre-existing `test_habit_status_tool_returns_history` failure is acceptable (failed on master before this work).

- [ ] **Step 2: Full frontend test**

```bash
cd services/web && npm test -- --run
```

- [ ] **Step 3: Frontend build**

```bash
npm run build
```

- [ ] **Step 4: Push**

```bash
git push origin master
```

CI builds; Watchtower picks up. Smoke-check on `10.0.6.16:8080` once deployed:

```bash
curl -sS -H "X-API-Key: hacktheplanet" "http://10.0.6.16:8080/coach/kiosk" | jq '{phase, lights_out_at, wind_down_mode, coach, anchors}'
```

Expected: `phase` is one of `day`/`wind-down`/`late`, `lights_out_at` is an ISO timestamp, `wind_down_mode` is boolean.
