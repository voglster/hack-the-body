# Coach v2 — Design

**Date:** 2026-05-10
**Status:** Draft, pending review
**Supersedes:** behavior in `services/api/app/services/coach.py` (single-shot generator) and the prompt-tar-pit workflow in `docs/coach-debugging.md`

## Goal

Make the coach actually coach. Today it narrates the snapshot it was handed
and the prompt has grown into a 70-line wall of negative guard-rails. v2
turns it into a thinking partner: still produces the daily brief on the
dashboard, but the brief becomes turn 1 of a conversation the user can
reply to. The model gets bounded tools to pull more data on demand, durable
memory across days, and a habits system so non-health daily things ("bed
by 10", vitamins, journal, make the bed) are first-class context — some
auto-resolved from existing data, some self-reported, some just named.

## Non-goals

- Telegram, voice, push notifications. The surface model is web dashboard
  only for v2. Core is designed surface-agnostic so Telegram plugs in
  later without redesign.
- Code-execution sandbox (PHIA-style `run_python`). Future tool; out of
  scope. The tool registry is the seam where it slots in.
- Multi-agent role split (Analyst / Domain Expert / Coach). One LLM role
  for v2. Revisit when prompt clarity demands it.
- Re-architecting Garmin ingestion, food logging, treadmill, or any data
  source. v2 only changes how the coach consumes them.

## Approach

Two paths share one context builder and one tool registry:

- **Brief path** — scheduled or on-demand. Deterministic Python preflight
  builds a rich `Findings` object (snapshot + trends + deltas + anomalies
  + habit statuses + memories). One LLM call, no tool loop. Becomes turn 1
  of a new conversation thread.
- **Chat path** — user replies to the thread. Agent loop, max 6 tool-call
  iterations per turn. Tools handle the open-ended cases the snapshot
  doesn't cover, plus memory writes and habit toggles.

The brief is the cheap, reliable, daily-driver path. The agent loop only
runs where it earns its keep.

## Components

All under `services/api/app/services/coach/` (new package; current
`coach.py` becomes `brief.py`'s ancestor):

- **`context.py`** — `build_findings()`. Extends today's `gather_context` +
  `today_food_totals` with:
  - 7-day and 30-day rolling trends per metric (sleep score, HRV, weight,
    steps, calories, protein).
  - Week-over-week deltas.
  - Anomaly flags ("HRV 22% below 30d baseline", "weight up 3lb in 4d").
  - Today's habit statuses.
  - Active explicit memories.
  - Recent unconfirmed implicit memories.
  - Bucketed lists: `on_track: [...]`, `attention: [...]`.
- **`brief.py`** — one-shot brief generator. Evolution of today's
  `generate_insight`. Reads `Findings`, renders prompt, single LLM call,
  saves as turn 1 of a new `coach_threads` doc plus a `coach_insights`
  row (for feedback continuity).
- **`chat.py`** — agent loop for replies. Loads thread + rebuilds fresh
  `Findings`, runs tool loop, appends a turn.
- **`tools.py`** — tool registry. Each tool is a plain async Python
  function with a JSON schema; registry handles dispatch, error wrapping,
  and per-tool token caps on results. Initial set:
  - `trend(metric, window_days)` — rolling avg + slope.
  - `compare_windows(metric, window_a, window_b)` — e.g. last 7d vs prior 30d.
  - `food_history(start, end)` — daily totals over a range (not raw entries).
  - `habit_status(name, days_back=7)` — done/missed counts.
  - `mark_habit_done(name, date?)` — defaults to today.
  - `remember(key, value, expires_at?)` — write explicit memory.
  - `recall(key?)` — read explicit memories (no arg = list all active).
  - `list_implicit_memories(status="candidate")` — debug/curation tool.
  - `promote_memory(implicit_id, key, value)` — promote candidate to explicit.
- **`memory.py`** — explicit + implicit memory repos. Implicit extractor
  pass (small LLM call over closed thread transcript → 0-N candidate
  facts).
- **`habits.py`** — habit config registry + daily status repo + auto-
  resolver dispatch. One function per resolver, registered by name.

## Data model

### New collections

- **`coach_threads`**
  ```
  {
    _id, started_at, last_activity_at, closed_at?,
    surface: "web",
    turns: [
      {
        role: "coach" | "user",
        text,
        ts,
        tool_calls?: [{name, args, result, ms}],
        findings_snapshot?  // present on coach turns
      }
    ]
  }
  ```
  Turns inline. Threads are short-lived (~1 day); rotated when >50 turns
  or when a new brief generates.

- **`habits`** (config) — `{_id, name, kind: "auto"|"manual"|"none", resolver?, schedule?: {days_per_week?, time_window?}, active, created_at}`.

- **`habit_status`** — `{habit_id, local_date, status: "done"|"skipped"|"missed"|"unknown", source: "auto"|"manual"|"coach", noted_at}`. Auto resolvers backfill on read.

- **`explicit_memories`** — `{_id, key, value, created_at, expires_at?, source: "user"|"promoted_implicit"}`. Injected verbatim into every prompt as a `Known about client` block. Expired rows skipped, not deleted.

- **`implicit_memories`** — `{_id, text, extracted_at, source_thread_id, status: "candidate"|"promoted"|"pruned", confidence?}`. Candidates injected with an `(unconfirmed)` marker.

### Kept / evolved

- **`coach_insights`** — kept. Each insight now stores `thread_id`. Existing rows without thread still render. `prompt`, `system_prompt`, `food_totals`, `history_snapshot` capture fields stay — the prompt-tuning workflow is unchanged for briefs.
- **`coach_feedback`** — unchanged shape, but now references `(thread_id, turn_index)` so feedback can attach to a mid-thread reply, not just turn 1.

## Initial habit auto-resolvers

- **`bed_by_10`** — read sleep onset from latest Garmin sleep doc; compare to 22:00 local. `done` if onset ≤ 22:00, `missed` otherwise. `unknown` if no sleep record for the night.
- **`vitamins`** — check existing vitamins router's collection for today's row. `done` if logged, `unknown` otherwise.

Manual habits: user taps "done" on the Habits page, or tells the coach in
chat ("done my journal") and it calls `mark_habit_done`.

`none` habits: just listed as named nudges; no status tracking.

## Flows

### Brief

1. Trigger (scheduler or `/coach/insight`).
2. `build_findings()` runs deterministic preflight.
3. `render_brief_prompt(findings, last_thread_summary)` produces the
   prompt — pre-digested, not raw JSON.
4. Single LLM call, no tool loop.
5. Create new `coach_threads` doc with turn 1 = `{role: "coach", text,
   findings_snapshot}`. Save `coach_insights` row pointing at the thread.

### Chat reply

1. User sends message via web chat panel into a thread.
2. Load last N turns + rebuild fresh `Findings`.
3. Agent loop:
   - System prompt + findings + memories + thread history + user message.
   - Model emits either final text or a tool call.
   - Tool calls dispatched through registry; errors returned as
     `{error: "…", hint?: "…"}` JSON for model recovery.
   - Hard cap 6 iterations. On cap, force a final text turn.
4. Append turn `{role: "coach", text, tool_calls: […]}`.
5. Update `last_activity_at`.

### Thread close + implicit extraction

1. Thread closes on idle (>2h since `last_activity_at`) OR when the next
   brief generates a new thread.
2. Extractor pass: small LLM call over the closed transcript → 0-N
   candidate facts.
3. Candidates land in `implicit_memories` with `status: "candidate"`.
4. Memory page (Implicit tab) lists candidates with promote/edit/prune.

## Frontend

- **Dashboard:** existing coach insight remains; under it, a chat panel.
  Tap-to-expand. Thread persists for the day; new brief = new thread.
- **More → Memory:** two tabs.
  - *Explicit*: CRUD on `explicit_memories` (key/value/expires_at).
  - *Implicit*: list of candidates; promote / edit-then-promote / prune.
- **More → Habits:** today's habit list with status indicators; per-habit
  toggle for manual ones; "+ New habit" form (kind, resolver name for
  auto, schedule).

## API additions

- `GET /coach/thread/active` → current thread (today's brief + turns).
- `POST /coach/thread/{id}/reply` → user message, returns coach turn.
- `GET /coach/threads?limit=` → recent threads (for a history view).
- `GET/POST/PATCH/DELETE /memory/explicit` → explicit memory CRUD.
- `GET /memory/implicit?status=candidate` → list candidates.
- `POST /memory/implicit/{id}/promote` → promote to explicit.
- `POST /memory/implicit/{id}/prune` → mark pruned.
- `GET /habits`, `POST /habits`, `PATCH /habits/{id}` → habit config.
- `GET /habits/today` → today's status (auto-resolved on read).
- `POST /habits/{id}/status` → manual mark.

All same-origin, gated by existing `api_key` mechanism.

## Error handling

- **Tool errors** caught at registry boundary, returned to model as JSON.
  Never throw out of the loop.
- **Iteration cap (6)** → synthetic error to model, forces final text turn.
- **LLM brief timeout** → retry once; on second failure, render a
  deterministic fallback brief from `Findings` ("Sleep 7h. Steps 8k.
  On-track: 3/4 habits.") so the dashboard never goes blank. Insight
  marked `model: "fallback"`.
- **LLM chat timeout** → "coach hiccup, try again" in the panel; no
  half-turn saved.
- **Memory write failure** → `remember` confirms success only after the
  Mongo write returns; failure surfaces as a tool error.
- **Habit auto-resolver failure** → return `status: "unknown"`; never
  block `Findings`.

## Testing

- **Unit:** `build_findings` against fixed Mongo fixtures (pin expected
  JSON). Each habit resolver. Each tool function. Memory repos (TTL
  respected, expired explicit memories not injected, candidates only
  injected with `(unconfirmed)`). Implicit extractor against canned
  thread transcripts.
- **Integration:** full brief generation with mock LLM. Full chat turn
  driving mock LLM through 2-3 tool calls including an intentional tool
  error. Thread-close triggers extraction. Feedback attaches to a
  mid-thread turn.
- **Regression pins:** keep existing prompt-guard tests where the rule
  survives; delete the test along with any rule that becomes unnecessary
  because findings/tools replace it (e.g. "don't invent baselines").
- **Eval harness:** small fixture-replay tool that re-runs the model
  against captured `coach_feedback` rows after a prompt change. Automates
  the manual spot-check from `docs/coach-debugging.md`.

## Prompt cleanup

Target: `SYSTEM_PROMPT` under 30 lines (currently ~70). Each guard-rail
has a test pinning it.

Drop (replaced by structured data):
- "Don't invent baselines / TDEE" — `Findings.targets` carries actual
  numbers; `compare_windows` gives real baselines.
- "Trust current snapshot over older messages" — `Findings` is
  authoritative; thread history is conversational, not data.
- "Don't roll-call every metric" — keep, but shorter; instruct model to
  address only `Findings.attention` items and mention `on_track` by name
  only.

Keep (voice / tone / safety):
- Food window, units (lbs), time-of-day reasoning.
- On-track close phrasing.
- Clinical-alarmism vocabulary ban.
- No-scolding rule.

## Rollout (slices)

Ship behind feature flag `COACH_V2_ENABLED`. Each slice is shippable
alone; later slices add behavior but don't depend on undesigned future
slices.

1. **Findings + brief path.** Replace `gather_context` with
   `build_findings`. Brief uses pre-digested context. No tools, no chat
   panel. Should already improve briefs; lowest risk.
2. **Threads + chat panel + tool loop.** Brief becomes turn 1; chat
   panel; tool registry online with `trend`, `compare_windows`,
   `food_history`, `recall`.
3. **Habits.** Config + resolvers + status repo + Habits page;
   `habit_status` and `mark_habit_done` tools.
4. **Explicit memory.** Memory page (Explicit tab); `remember`/`recall`
   wired to durable storage.
5. **Implicit memory.** Thread-close extractor + Implicit tab on Memory
   page + `list_implicit_memories` / `promote_memory` tools.

Each slice gets its own implementation plan under
`docs/superpowers/plans/`.

## Open questions / deferred decisions

- **Model choice.** Current Ollama setup (GLM family) is fine for brief
  path. Tool-call reliability for chat path needs a bench before
  committing — BFCL v4 ranks GLM-4.5 at 76.7% and Qwen3-32B at 75.7%;
  for 2-4 tool-call chains either should work, but verify on a
  fixture-replay eval before slice 2 ships.
- **Thread retention.** Keep all threads forever (audit trail) vs.
  archive after N days. Default to keep-forever for v2; reconsider if
  Mongo bloats.
- **Implicit extractor model.** Same model as the coach, or a smaller
  cheaper one? Default to same model for v2; revisit when slice 5 ships.
- **Habit schedules.** v2 ships with daily-only habits (every day
  expected). `schedule.days_per_week` field is reserved but not honored
  until a real need arrives.
