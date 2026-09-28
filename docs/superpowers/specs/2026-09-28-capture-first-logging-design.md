# Capture-First Logging — Design

**Date:** 2026-09-28
**Status:** Approved direction
**Follows:** `2026-08-16-voice-food-entry-design.md`
**Next:** coach with memory + goals (separate spec) — takes over reminders

## Problem

Logging adherence is the lever. May 2026: logged 31/31 days, weight
113.0 → 108.8 kg. June–September: logging collapsed (6 entries in Sept)
and weight returned to 112.9 kg. The user avoids logging because every
path makes them *resolve* the food at the moment of capture — scan it,
search it, fix a misparse. Voice shipped in August and was used once.

A root cause in code: `parse_food_text` never consults the catalog. Every
paste/voice "premier vanilla" creates a fresh `source=paste|voice` Food
with LLM-guessed macros instead of matching the Vanilla Premier shake
logged 33 times with real label values.

## Guiding rule

**Low effort, high adherence.** Capture takes seconds and never blocks.
Confident matches log without asking. Only genuine uncertainty reaches
the user, as a one-tap choice they may ignore.

## Design

### 1. Captures — the inbox

New collection `captures` (regular, not time-series — it mutates):

```
{ _id, ts (when eaten), created_at, source: tap|text|voice|button,
  device: phone|kitchen|kiosk|ha|null,
  input: { text?, food_id?, quantity_g?, template_id?, button? },
  status: resolved|pending|needs_confirm|placeholder|failed,
  entry_ids: [..], candidates: [..] (needs_confirm only),
  attempts, last_error, resolved_at }
```

`meal_entries` stays the source of truth for totals. Every entry created
through capture carries `capture_id` so undo = delete capture + its
entries.

API (`/capture`):
- `POST /capture` — `{text}` or `{food_id, quantity_g?}` or
  `{template_id}` or `{placeholder: true}`, plus optional `ts`, `device`.
  Taps resolve inline (no LLM). Text returns immediately as `pending`
  and schedules resolution as a background task.
- `GET /capture/today` — today's captures (for the Log screen).
- `GET /capture/inbox` — `needs_confirm` + `placeholder` + `failed`.
- `POST /capture/{id}/confirm` — `{candidate_index}` or `{food_id,
  quantity_g}` or `{text}` (re-resolve). Confirming teaches the phrase.
- `DELETE /capture/{id}` — undo, cascades entries.
- `GET /capture/suggestions` — the grid.

Slot is inferred from local time of `ts`: <10:30 breakfast, <14:30
lunch, 17:00–21:00 dinner, otherwise snack; supplements keep
`supplement`, drinks keep `snack` (matches existing data).

### 2. Resolver

Order, per capture text:

1. **Learned phrases** (`capture_phrases`: normalized text → list of
   `{food_id, quantity_g}`). Exact hit → resolved, no LLM.
2. **Split + match.** LLM splits the text into items (existing parser,
   extended to return `quantity`/`unit` hints). Each item is fuzzy-
   matched against the catalog (name + brand tokens, rapidfuzz), scored
   and boosted by usage count. Score ≥ 85 → use that food with its
   last-used quantity (or the parsed count × serving). One item below
   threshold makes the whole capture `needs_confirm` with top-3
   candidates per item plus "new food (estimated)".
3. **New food** only when nothing matches: the LLM estimate becomes a
   `source=capture` Food (as today's paste path does).

Auto-resolved captures also teach their phrase (one-item phrases only,
to avoid learning bad combos from a single guess — reinforced on
confirm).

Failure: LLM down or error → `pending`, `attempts++`. A scheduler sweep
every 5 minutes retries pending captures (max 5 attempts → `failed`,
shown in the inbox with a "type it again" affordance). Nothing a user
captured is ever dropped.

Existing `/foods/parse/log` and `/foods/voice/log` are re-pointed to
create captures so there is one pipeline.

### 3. Suggestions grid

`GET /capture/suggestions?limit=8` — pure Python over the last 60 days
of `meal_entries`: score per food_id = Σ over entries of
`recency_decay(age, half-life 14d) × time_of_day_weight(|Δhour| of
entry vs now, σ=2h)`. Returns food name, default quantity (most recent
quantity_g), and category. Water and vitamins excluded (they have their
own buttons). Meal templates are included as grid items scored the
same way on their `template_id` entries.

### 4. Log screen

Route `/log`; `manifest.start_url` → `/log`. Components:

- **Inbox strip** — cards for `needs_confirm` / placeholder / failed;
  one tap on a candidate confirms.
- **Grid** — 2 columns on phone, 4 on iPad (`≥768px`); tap = capture +
  undo toast (6s).
- **Input bar** — text field + hold-to-talk mic (existing recorder).
  Enter/release = capture. The transcript becomes a text capture.
- **Today** — captures list with status chips; kcal + protein totals
  with "+N unresolved"; streak.
- Quick water (+8oz) and vitamins chips at the top.
- `?kitchen=1` requests a Screen Wake Lock and larger type.

Dashboard gets a prominent "Log" entry in the bottom nav.

### 5. IKEA buttons (Home Assistant)

- `capture_buttons` collection: `{button: "kitchen_remote/arrow_right_click",
  action: food|water|habit|placeholder|undo, food_id?, quantity_g?,
  habit_id?, label}`.
- `POST /capture/button` `{button}` → runs the mapped action, returns
  `{say: "Shake logged."}`. Unmapped → `{say: "That button isn't set up."}`.
- `undo` deletes the most recent button-sourced capture within 15 min.
- One HA automation per remote forwards every `zigbee2mqtt/<remote>/action`
  payload, and pipes `say` into the office-announce/Piper path.
- Default kitchen mapping: toggle → vitamins habit, up → water 8oz,
  right → Vanilla Premier shake, left → placeholder, down → undo.
- A simple settings list on the Log screen edits mappings.

### 6. Adherence loop

- **Streak** — consecutive local days with ≥2 non-water/vitamin food
  captures. Today counts once it qualifies.
- **Stopgap reminder** — scheduler at 11:00, 15:00, 20:00 local: if no
  food capture since the previous window, send a push ("Nothing logged
  since breakfast — tap to log.") linking `/log`. Replaced by the coach.
- **Kiosk** — a card: today logged?, streak, "+N to confirm", and the
  tracked-vs-untracked weight line computed from history (weight change
  over runs of logged vs unlogged weeks).
- `GET /capture/status` serves streak, pending count, today-logged
  flag, and the tracked/untracked summary for the kiosk and coach.

### 7. Live voice (later phase)

Port's live transcript (`port/frontend/src/utils/liveCapture.ts`,
`backend/app/deal/voice_live*.py`) onto the capture path, with batch
fallback. Own plan; not in slice 1.

## Build slices

1. Captures + resolver + suggestions + `/log` screen (typed + tapped +
   existing voice). **Ship and use.**
2. Buttons + HA automation + spoken confirmation.
3. Streak, stopgap reminders, kiosk card, `/capture/status`.
4. Live voice port.

## Testing

API tests (mongomock + patched LLM) for: tap capture, text → phrase hit,
text → catalog match, text → needs_confirm, confirm teaches phrase,
undo cascades, LLM failure leaves pending + sweep retries, suggestions
ranking, button mapping + undo. FE tests for the Log screen's tap/undo
and inbox confirm. End-to-end check on prod after deploy: log a shake
from the phone via text and via grid tap.

## Out of scope

Coach memory/goals/proactive voice (next spec). Workout logging.
Barcode flow changes (stays reachable from the Food tab).
