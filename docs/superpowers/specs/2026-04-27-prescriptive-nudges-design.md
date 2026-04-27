---
status: active
created: 2026-04-27
related:
  - 2026-04-27-protocol-system-vision.md
  - 2026-04-27-sleep-accountability-loop-design.md
---

# Prescriptive Nudges — Design

## Intent

Shift the app from passive logging to a prescriptive surface. The dashboard
gains a top-of-page "Today" card that tells the user what to do right now
(drink water, take vitamins, weigh in, get to bed) and what they've missed.
A small subset of nudges also fire as web push notifications at fixed times
of day. This is the foundation for the broader protocol-management vision
(see `2026-04-27-protocol-system-vision.md`); the data model and code paths
are generic over protocol kind so non-health protocols slot in later without
schema changes.

The retrospective "what happened?" loop for blown bedtimes and other
adherence failures is **out of scope** — see
`2026-04-27-sleep-accountability-loop-design.md`.

## v1 nudge list

| ID | Kind | Floor (don't fire before) | Fires when | Push? |
|---|---|---|---|---|
| `vitamins_missing` | vitamin | 12:00pm | No vitamin entries today | 12:00pm |
| `water_below_pace` | water | 10:00am | Intake < target × elapsed × 0.7 | — |
| `no_weighin` | weight | 10:00am | No Garmin weight reading for today | 10:00am |
| `steps_below_pace` | steps | 12:00pm | Steps < target × elapsed × 0.6 | — |
| `bedtime_reminder` | bedtime | 9:30pm | Always, until 10:30pm | 9:30pm |

`elapsed` = fraction of the 6am–10pm waking window passed at evaluation
time. Pace math: at 1pm, elapsed = 7/16 = 0.4375.

Workouts are **not** in v1: no schedule source until Hevy ingestion lands.
Sleep-miss retrospective is Spec B.

## Architecture

```
                  ┌──────────────────────────┐
                  │  services/nudges.py      │
                  │  rules registry          │
                  │  evaluate(now, ctx) →    │
                  │    list[FiredNudge]      │
                  └────────────┬─────────────┘
                               │
            ┌──────────────────┼─────────────────┐
            │                  │                 │
   GET /nudges          POST /nudges/dismiss   push cron
   (dashboard pulls)    (per-day suppress)     (3 time-anchored)
            │                                    │
            ▼                                    ▼
  Today's-nudges card                     existing push.py
```

The rules engine is **stateless and pure**: given `(now, user-data context,
dismissals)`, returns the currently-firing nudges. Recomputed on every
`GET /nudges` and every push-cron tick. No "nudge events" table — fired
nudges are not persisted in v1. (Persisting events for predictive nudging
is a future change called out in the vision doc.)

Dismissal is a **thin overlay**: a per-day Mongo doc `nudge_dismissals` with
`{ nudge_id: dismissed_until_ts }`. The engine filters out dismissed rules
when rendering and when pushing.

Rules are **generic over protocol kind**: each `Rule` has `id`, `kind`,
`pushable`, `push_at`, and an `evaluate(ctx)` callable. Adding a future
"bass practice" protocol means appending a rule, not changing the engine.

## Components

### Backend (`services/api/app/`)

- **`services/nudges.py`** *(new)* — pure rules engine.
  - `Rule` dataclass: `id`, `kind`, `pushable: bool`, `push_at: time | None`,
    `evaluate(ctx) → FiredNudge | None`.
  - `FiredNudge` dataclass: `id`, `kind`, `severity` (`info` | `warn`),
    `title`, `body`, `dismissable: bool`.
  - `RULES: list[Rule]` — module-level registry. Five entries for v1.
  - `evaluate_all(ctx, now, dismissals) → list[FiredNudge]` — runs each
    rule inside `try/except`, filters out dismissed-until-now, returns
    fired nudges in `RULES` registry order (deterministic; render order
    is tunable by reordering the registry).
  - `build_context(db, user, now)` — gathers everything rules need in one
    pass: targets doc, today's vitamin entries, today's water total,
    today's Garmin weight, today's steps. Shared across rules.
  - **All thresholds + the 6am–10pm day window live as module constants
    at the top of this file.** One place to tune.

- **`routers/nudges.py`** *(new)*:
  - `GET /nudges` → `{ nudges: [FiredNudge, ...], generated_at }`
  - `POST /nudges/dismiss` body `{ nudge_id, until: iso_ts | "end_of_day" }`.
    Upserts to `nudge_dismissals`.

- **Mongo collection `nudge_dismissals`** *(new)*:
  - Doc shape: `{ _id: "<user>_<YYYY-MM-DD>", entries: { vitamins_missing: <iso_ts>, ... } }`.
  - One read per `GET /nudges`. No TTL needed at this scale.

- **Push cron** — extend existing scheduled-push infra in `push.py`:
  - Three buckets per local day: 10:00, 12:00, 21:30.
  - Each tick: build context, evaluate only rules with `push_at == bucket`,
    skip dismissed, send web push for whatever fires.
  - Reuses existing VAPID + subscription plumbing, including 410 →
    unsubscribe handling. No new push infrastructure.
  - Bucket grace window ±5 min; later than that, log and skip.

### Frontend (`services/web/src/`)

- **`components/NudgesCard.tsx`** *(new)* — top-of-dashboard card.
  - Fetches `/nudges` on mount and on dashboard refresh.
  - Header "Today" + bulleted list, one icon per `kind`, body text, ×
    button per row.
  - × calls `POST /nudges/dismiss` with `until: "end_of_day"`,
    optimistically removes row.
  - Renders `null` when `nudges` is empty (absence is the reward).

- **`pages/Dashboard.tsx`** — mount `<NudgesCard />` above existing cards.
- **`api/nudges.ts`** *(new)* — `fetchNudges()`, `dismissNudge(id, until)`.

## Data flow

### Dashboard load

```
Browser → GET /nudges
  ↓
nudges router →
  build_context(db, user, now):
    - read user_profile.targets
    - read today's vitamin entries
    - read today's water total
    - read today's Garmin weight
    - read today's steps
  read nudge_dismissals[user_today]
  evaluate_all(ctx, now, dismissals)
  ↓
[FiredNudge, ...] → JSON
  ↓
NudgesCard renders
```

All reads are today-only and indexed by date. No new caching layer.

### Dismissal

```
User clicks × → optimistic remove → POST /nudges/dismiss
  ↓
upsert nudge_dismissals[user_today].entries[nudge_id] = end_of_day_ts
  ↓
next dashboard fetch filters that nudge out
```

`end_of_day` resolves server-side to 23:59:59 in the user's local TZ.
Future "snooze 1h" support drops in by sending an explicit ISO timestamp;
no schema change.

### Push tick

```
Cron at 10:00 / 12:00 / 21:30 local
  ↓
for each user with push subscriptions:
  ctx = build_context(db, user, now)
  dismissals = read nudge_dismissals[user_today]
  for rule in RULES where rule.push_at == now-bucket:
      fired = rule.evaluate(ctx)
      if fired and not dismissed:
          send_web_push(user, fired.title, fired.body)
```

Dismissal beats push: dismissing `vitamins_missing` at 11:55am suppresses
the 12:00 push. A push that fires at 10:00 for a missed weigh-in is **not**
auto-dismissed — it stays on the dashboard until the user weighs in or
dismisses.

### Day rollover

Dismissals are scoped to `<user>_<local-date>`. The first request after
midnight reads a doc that doesn't exist yet → empty dismissals → all rules
evaluate fresh. No background job needed.

### Timezone

Reuses the TZ-aware "today" helper introduced in commit `0e63b77`
(scheduled coach push fix).

## Error handling

**Rules engine fails open.** A bug in one rule must not blank the whole
nudges card. `evaluate_all` runs each rule inside `try/except`; exceptions
are logged with the rule id and skipped. Sibling rules render normally.

**Missing data is "no nudge," not an error:**

- No targets doc → pace-based rules silent; binary rules (vitamins,
  weigh-in, bedtime) still work.
- No Garmin steps doc for today → `steps_below_pace` skips (can't
  distinguish "behind" from "not yet ingested"). `no_weighin` still fires
  — absence of weight data **is** the signal there.
- Never logged a vitamin → `vitamins_missing` fires after noon. Correct.

**Dismissal API:**

- Unknown `nudge_id` → 200, no-op (FE may be slightly out of sync).
- Malformed `until` → 422 from pydantic.

**Push tick:**

- Each user's evaluation wrapped in `try/except`; one user's bad data
  doesn't abort the cron run.
- `send_web_push` failure logged and swallowed; existing 410 →
  unsubscribe handling reused.
- Late tick within ±5 min still fires; >5 min skips with a log.

**Frontend:**

- `GET /nudges` 5xx → `NudgesCard` renders nothing. Same posture as the
  existing `CoachCard`.
- Dismissal POST fails after optimistic removal → toast and row reappears
  on next fetch.

## Testing

### `services/api/tests/test_nudges.py`

Table-driven, one parametrize block per rule:

- **Threshold boundaries** — floor time ±1 min.
- **Pace math** — verified examples at multiple times of day, with and
  without targets present.
- **Binary rules** — logged vs. not, weight present vs. absent.
- **Bedtime window** — 9:29pm no fire, 9:30pm fire, 10:31pm no fire.
- **Day rollover** — 11:59pm vs. 12:01am uses correct local-date.
- **Dismissal filtering** — active vs. expired entries.
- **Fail-open** — raising rule is logged and skipped; siblings unaffected.
- **Missing data** — no targets / no steps / no vitamins paths.

### `services/api/tests/test_nudges_router.py`

- `GET /nudges` shape and auth.
- `POST /nudges/dismiss` writes doc; subsequent `GET` filters that nudge.
- Unknown `nudge_id` → 200 no-op.
- `until: "end_of_day"` resolves to local-TZ 23:59:59.

### Push cron unit tests

- `tick(10:00)` evaluates only `push_at == 10:00` rules and sends pushes.
- Dismissed rules don't push.
- Late tick within ±5 min fires; >5 min skips.
- One user's exception doesn't abort the loop.

### `services/web/src/components/NudgesCard.test.tsx`

- Renders a row per fired nudge.
- Empty list → returns `null`.
- × click → optimistic remove + dismiss API call.
- Failed dismissal → row reappears on next fetch.
- Loading/error → renders nothing.

### Out of test scope

Vite glue, FastAPI route registration, cron scheduler config — boilerplate
per project conventions.

## Future hooks (not in v1)

Called out so v1 doesn't accidentally close doors:

- **Persist fired nudges as events** for predictive nudging and history.
  Add a `nudge_events` collection later; engine signature stays the same.
- **Snooze with arbitrary `until`** — already supported by the dismissal
  API shape; FE just needs UI.
- **Configurable thresholds in profile** — move constants out of
  `nudges.py` into the targets doc; one-day change.
- **Non-health protocols** — append rules with new `kind` values; the
  rules engine already handles them generically.
- **Sleep accountability loop** — Spec B hooks into the deviation events
  surfaced here.
