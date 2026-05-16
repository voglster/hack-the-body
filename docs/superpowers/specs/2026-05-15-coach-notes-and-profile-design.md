# Coach Notes & Profile — Design

**Date:** 2026-05-15
**Status:** Draft, approved direction (option C)
**Related:** `services/api/app/services/coach/brief.py`, `services/api/app/services/coach/context.py`, `services/api/app/routers/profile.py`

## Problem

The kiosk coach has two recurring blind spots:

1. **No same-day context.** Jim might be eating dinner out, fasting through lunch on purpose, or skipping the gym for a reason. The coach reads only metrics and has no idea — it ends up suggesting "EAT" or flagging low calories when Jim deliberately wants to be light.
2. **No standing stance.** Jim is in a slow weight-loss phase. Being under his calorie target is generally *fine*, even *desired*, and the coach should weight that accordingly. Right now the deterministic Attention rule (`bucket_metrics` in `context.py:159`) treats `calories < 75% of target` as something to nag about, regardless of intent.

## Goal

Give the coach two new context channels, tune one Attention rule, and unify the two prompts so persona + rules are shared:

1. **Day note** — short ephemeral text Jim writes today, reset at local midnight.
2. **Coach profile** — long-lived stance/goals Jim edits rarely.
3. **Softened calorie rule** — being under calories alone no longer trips Attention when the profile flags Jim as cutting.
4. **Unified coach core** — one shared persona/voice/rules block consumed by both the kiosk glance-line and the main scheduled/dashboard coach; the surfaces only differ in their output-shape declarations.

Both notes editable from the dashboard.

## Architecture

### Storage — extend the existing `user_profile` collection

Mirrors the existing `_id="targets"` pattern in `routers/profile.py`.

- **`_id="day_note"`** — `{ text: str, set_at: datetime, local_date: str }`. `local_date` is the YYYY-MM-DD of Jim's wall clock at write time. Used as the dedupe key for "is this still today's note?" — when `local_date` ≠ today (per `TZ` env), treat the note as empty.
- **`_id="coach_profile"`** — `{ text: str, updated_at: datetime }`. Free-form markdown-ish text. No schema. ~500 char soft cap (the LLM should not be reading a manifesto).

Two separate docs because lifecycles differ: day note resets daily, profile drifts over months.

### API — two new sibling endpoints in `routers/profile.py`

```
GET  /profile/day-note    → { text, local_date, is_today }
PUT  /profile/day-note    → body { text }
DELETE /profile/day-note  → clears today's note

GET  /profile/coach-note  → { text, updated_at }
PUT  /profile/coach-note  → body { text }
```

`is_today` on the GET is a server-computed convenience so the dashboard doesn't have to redo the TZ math.

Helpers for the coach service (matching `get_user_targets` pattern):

```python
async def get_day_note(db) -> str | None  # returns None when stale
async def get_coach_profile(db) -> str | None
```

### Prompt composition — one core, two tails

Today there are two unrelated prompts (`SYSTEM_PROMPT`, `KIOSK_SYSTEM_PROMPT`) that have drifted: the kiosk has the new pit-crew voice and the day-note/profile awareness will land first there, the main coach is still on the old prose persona. This refactor fixes that.

Replace the two flat constants with three composable pieces in `brief.py`:

```python
COACH_CORE = (
    # Persona — pit crew chief / strength coach voice (the same block
    # that's now in KIOSK_SYSTEM_PROMPT, extracted)
    # Voice rules — second person, no butler, no cheerleader
    # Food / time / weight / fasting-window rules
    # Day-note block — rendered only if set
    # Coach-profile block — rendered only if set
    # Attention contract — Attention is authoritative
)

KIOSK_TAIL = (
    # "Output STRICT JSON with verb / qualifier / urgency / coach."
    # JSON-field definitions, including the 6-12 word coach sentence
    # and the CLEAR-state guidance block.
)

BRIEF_TAIL = (
    # "Output prose. Under 120 words on Attention, under 40 when
    #  on track. Address only Attention items + one concrete action."
)

KIOSK_SYSTEM_PROMPT = COACH_CORE + KIOSK_TAIL
SYSTEM_PROMPT       = COACH_CORE + BRIEF_TAIL
```

Concrete benefits:
- Voice fixes land in both surfaces from one edit.
- Day-note + profile injection is described once in `COACH_CORE`, not duplicated.
- Surface drift becomes structurally impossible — the only thing surfaces *can* disagree on is output shape, which is what should differ.

The current `SYSTEM_PROMPT` content (the longer prose-coach guidance) gets folded into `COACH_CORE` where it overlaps and `BRIEF_TAIL` where it's surface-specific (length, prose vs JSON).

### Coach context — feed into `build_findings` / `render_brief_prompt`

In `context.py`, `Findings` gains two optional fields:

```python
day_note: str | None = None
coach_profile: str | None = None
```

`build_findings` reads both via the helpers above. `brief.py::render_brief_prompt` injects them into the prompt right above `Client:` (same block for both surfaces — no per-prompt branching):

```
Today's note from Jim: "dinner out at friend's tonight, intentionally light through afternoon"

Standing profile:
trying to lose weight slowly (~0.5 lb/week). Being under calories is fine
when activity is also low or moderate. Flag low calories only when paired
with low protein or very high activity.

Client:
...
```

Both blocks are omitted entirely (no header) when their value is `None` / empty — keeps the prompt clean on a "no notes set" day.

### Attention rule tuning — `bucket_metrics`

Current rule (`context.py:159`):

```python
if calories < target * 0.75 and food_logged:
    attention.append("calories")
```

New rule, profile-aware:

```python
if calories < target * 0.75 and food_logged:
    cutting = bool(coach_profile)  # ← any standing profile present means "trust Jim's intent"
    activity_high = steps_today > step_goal  OR  active_kcal > 500
    protein_low = protein_g < target_protein * 0.6
    if (not cutting) or activity_high or protein_low:
        attention.append("calories")
```

Plain English: when Jim has set a coach profile (which always frames him as cutting in his case), being under calories alone is fine. It only escalates to Attention when paired with high activity (so he'll be exhausted tomorrow) or low protein (so he's actually losing muscle, not fat).

This is the smallest defensible change. The profile text itself is opaque to this rule — *any* non-empty profile is treated as "Jim has thought about this, don't nag." If later Jim wants different stances at different times, a structured `cutting: bool` field gets added to the profile doc and this rule reads that instead. Not needed now.

### Frontend — one new dashboard component

`CoachNotesCard.tsx`, slotted into `Dashboard.tsx` near the top (high enough to glance, not so high it pushes metrics down). Two stacked text areas:

- **Today's note** — single-line input, placeholder "what's the coach should know about today?", auto-clears at local midnight via `is_today` from the API. Save on blur or Cmd-Enter.
- **Coach profile** — multi-line textarea, "your standing stance — edit rarely". Save on blur.

Both fields show last-saved timestamp underneath. No persistence indicator beyond that — autosave + visible timestamp is the contract.

Kiosk page is **not** changed in this spec. Editing happens on the dashboard only, by design (matches Jim's pick).

## Testing

- `routers/profile.py` — round-trip GET/PUT/DELETE for both endpoints; `is_today` flips correctly across a fake midnight.
- `context.py::bucket_metrics` — three new tests:
  - profile present, low calories alone → NOT on attention
  - profile present, low calories + high activity → on attention
  - profile present, low calories + low protein → on attention
- `brief.py::render_brief_prompt` — day-note and profile blocks appear when set, are omitted when empty.
- `brief.py` prompt composition — both `KIOSK_SYSTEM_PROMPT` and `SYSTEM_PROMPT` contain `COACH_CORE` verbatim; each has its own tail's distinguishing marker (`"STRICT JSON"` vs `"prose"` length guidance).
- `services/web` — Vitest for the card: typing + blur saves, midnight-rolled note shows empty input.

## Out of scope (intentional)

- Multi-day notes / a calendar of past notes. The day note is intentionally write-once-read-many-then-gone.
- Per-meal notes ("this lunch was protein-heavy"). The day note is the right grain for now.
- Editing the profile from the kiosk or via Telegram. Dashboard-only this round; future Telegram coach work can add commands later.
- Inferring `cutting: bool` from profile text via LLM. Avoid added complexity until the binary "profile set or not" stops being enough signal.

## Rollout

One PR, all layers in one drop, deploy via the normal CI → Watchtower path. No migration — `user_profile` already exists, new docs are upserted on first write.
