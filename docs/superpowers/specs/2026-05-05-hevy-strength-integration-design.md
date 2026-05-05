# Hevy Strength Workout Integration — Design

**Status:** Draft
**Date:** 2026-05-05
**Phase:** 1.x extension (data spine)

## Goal

Pull strength workouts logged in Hevy (bodyweight + weighted lifting)
into the existing `workouts` collection, plus capture per-set detail
in a new `strength_sets` collection, so the dashboard can show "what
did I do this week" mixing cardio (Garmin, treadmill) and strength
(Hevy) — and so future analytics (volume trends, PRs, coach prompts)
have structured data to query.

## Non-goals

- Pushing data **into** Hevy. One-way pull only.
- Real-time per-set streaming during a live workout. Webhook fires on
  workout completion; live in-progress state stays in the Hevy app.
- Exercise template normalization / muscle group taxonomy. Exercise
  titles are stored as strings ("Incline Push Ups"). Grouping by
  muscle group is a future concern.
- Migrating existing Garmin or treadmill workout shape. New strength
  rows coexist with cardio rows in the same `workouts` collection.

## Sync model

Two paths converge on identical upsert logic:

1. **Webhook (push, near-real-time).** Hevy POSTs to
   `https://htb.home.vogelcc.com/webhooks/hevy` when a workout is
   created, updated, or deleted. The handler validates the bearer
   token, writes a `requested` row to `ingestion_log` carrying the
   workout id and event type, and returns 204 in <500ms. The Hevy
   ingestor service watches that log (same pattern Garmin uses for
   `POST /admin/ingest/garmin`) and processes the event.
2. **Cron poll (backstop).** Every 6 hours the ingestor calls
   `GET /v1/workouts/events?since=<cursor>` to catch anything the
   webhook missed (network blip, Hevy outage, deleted webhook).
   The cursor is stored in `ingestion_log` on the most recent
   successful Hevy run.

Both paths land in the same processing function:

```
process_workout_event(event_type, workout_id):
    if event_type == "deleted":
        delete workout + cascade delete strength_sets
        return

    incoming = hevy_api.get_workout(workout_id)
    existing = workouts.find_one({source_id: f"hevy:{workout_id}"})

    if existing and existing.updated_at >= incoming.updated_at:
        return  # no-op

    upsert workouts row (replace if existing)
    delete strength_sets where workout_source_id == f"hevy:{workout_id}"
    insert one strength_sets row per set
```

The webhook payload itself is **not** trusted as data — only as a
trigger. The handler always re-fetches from Hevy's API, so a leaked
webhook URL cannot inject fake workout data; worst case an attacker
forces extra API calls (rate-limited by Hevy).

## Security: webhook endpoint

`POST /webhooks/hevy` is the only public Hevy surface.

- **Shared secret** in `Authorization: Bearer <HEVY_WEBHOOK_SECRET>`.
  Generate with `openssl rand -hex 32`. Set when registering the
  webhook with Hevy. The handler 401s if the header is missing or
  doesn't match.
- **Method-locked.** POST only. GET / OPTIONS / etc. → 405.
- **Schema-validated.** Pydantic model on the body; reject malformed
  payloads with 400 (don't leak parse errors to the caller).
- **Fast.** Handler enqueues to `ingestion_log` and returns 204
  within 500ms. No synchronous Hevy API call inside the handler.
- **Idempotent.** Multiple webhook fires for the same workout id
  collapse via the `updated_at` version check downstream.

`HEVY_API_KEY` and `HEVY_WEBHOOK_SECRET` both live in `.env` (one for
calling Hevy, one for verifying inbound). Both are documented in
`compose/.env.example` with the Pro-only caveat.

## Data model

### `workouts` (existing, additive change)

One row per Hevy session. Same shape as cardio workouts; only the
`activity_type` differs.

| Field | Type | Notes |
|---|---|---|
| `ts` | datetime | `start_time` from Hevy, UTC |
| `activity_type` | str | `"strength"` |
| `duration_s` | int | `end_time - start_time` |
| `distance_m` | float \| None | always None for Hevy |
| `avg_hr` | int \| None | usually None (Hevy doesn't capture HR) |
| `max_hr` | int \| None | same |
| `calories` | int \| None | Hevy doesn't return; None |
| `source` | str | `"hevy"` |
| `source_id` | str | `f"hevy:{workout_id}"` (UUID-based) |
| `updated_at` | datetime | from Hevy `updated_at`; **new field** |
| `title` | str \| None | from Hevy (e.g., "Push Day"); **new field** |
| `exercise_count` | int \| None | derived; **new field**, strength only |
| `set_count` | int \| None | derived; **new field**, strength only |
| `raw` | dict | full Hevy workout JSON |

The unique index on `source_id` already exists (`db.py:45`). The
three derived fields (`title`, `exercise_count`, `set_count`) are
nullable additions — Garmin/treadmill rows leave them as None. They
exist to avoid joining `strength_sets` for the list view.

### `strength_sets` (new collection)

One document per logged set. Regular collection (not time-series) so
we can replace-by-parent on workout updates.

| Field | Type | Notes |
|---|---|---|
| `workout_source_id` | str | foreign key, e.g., `"hevy:abc-123"` |
| `ts` | datetime | inherited from parent workout `start_time` |
| `exercise_index` | int | 0-based, ordering within workout |
| `exercise_title` | str | "Incline Push Ups" |
| `exercise_template_id` | str | Hevy's stable id (`"39C99849"`) |
| `set_index` | int | 0-based, ordering within exercise |
| `set_type` | str | `"normal"`, `"warmup"`, `"failure"`, `"dropset"` |
| `reps` | int \| None | |
| `weight_kg` | float \| None | None for bodyweight |
| `distance_m` | float \| None | for cardio-flavored exercises |
| `duration_s` | int \| None | for timed sets (planks etc.) |
| `rpe` | float \| None | rate of perceived exertion |
| `superset_id` | str \| None | groups supersetted exercises |
| `notes` | str \| None | per-exercise note from Hevy |

Indexes:
- `[("workout_source_id", 1), ("exercise_index", 1), ("set_index", 1)]`
- `[("exercise_template_id", 1), ("ts", -1)]` — for "show me all my
  pull-up sets" queries (future PR tracking).

No unique index — replace-and-reinsert by `workout_source_id` on
update is the correctness mechanism, identical to how the treadmill
aggregator handles its `workouts` rows.

## Service layout

New service: `services/ingestor-hevy/`. Mirrors `ingestor-garmin/`:

```
services/ingestor-hevy/
  app/
    __init__.py
    config.py        # Settings (HEVY_API_KEY, schedule, db conn)
    hevy_client.py   # thin httpx wrapper, api-key header
    models.py        # Pydantic: HevyWorkout, HevyExercise, HevySet
    mappers.py       # hevy_workout_to_workout(), hevy_workout_to_strength_sets()
    repo.py          # upsert_workout(), replace_strength_sets(), delete_workout()
    runner.py        # main loop: poll ingestion_log + cron events
    main.py          # entry point
  tests/
    test_mappers.py
    test_repo.py
    test_runner.py
  Dockerfile
  pyproject.toml
```

Container ships as `ghcr.io/voglster/hack-the-body-ingestor-hevy`.
Added to `.github/workflows/build.yml` alongside the other two
images, and to `compose/docker-compose.yml`. Watchtower picks it up
once the container name is added to its watch list (per CLAUDE.md
deploy procedure).

The webhook **endpoint** lives in the API service
(`services/api/app/routers/webhooks.py`), not the ingestor — the
API is the public-facing service. The endpoint's only job is
validate-and-enqueue.

## API additions

- `POST /webhooks/hevy` — webhook receiver (described above).
- `GET /workouts/{source_id}` — single workout detail. For strength,
  joins `strength_sets` (sorted by `exercise_index`, `set_index`)
  and returns:
  ```
  {
    ...workout fields...,
    "exercises": [
      {
        "title": "Incline Push Ups",
        "template_id": "39C99849",
        "notes": "5th step",
        "sets": [{ "reps": 12, ... }, ...]
      },
      ...
    ]
  }
  ```
  For non-strength workouts, `exercises` is omitted (or empty).
- `GET /workouts` (existing) — no contract change for callers, but
  rows now include `title`, `exercise_count`, `set_count` when
  present. Backwards-compatible additions only.

## Frontend

Per UX architect's call: keep bottom nav at 4 slots. Add a
**Workouts** entry to the **More** tab as the primary entry point.

### Routes

- `/workouts` — list view (mixed cardio + strength), grouped by
  local-time date, last 30 days. Reuses the existing
  `GET /workouts?days=30` endpoint.
- `/workouts/:source_id` — detail view. For strength, renders the
  exercise/set table. For treadmill (active), renders the existing
  live-workout UI from `pages/Workout.tsx`. For Garmin cardio,
  renders the basic summary card.

### List view

Phone-friendly, day-grouped, type-aware:

```
Mon May 4
  🏋  Push Day · 42min · 6 ex · 18 sets   >
  🏃  Treadmill · 28min · 2.1mi          >
Sun May 3
  🚶  Walk (Garmin) · 51min · 3.4mi      >
```

Strength rows show `title`, duration, exercise count, set count.
Cardio rows show duration, distance. Both → tap for detail.

### Detail view (strength)

```
Push Day                            Mon May 4 · 42min
─────────────────────────────────
Incline Push Ups                  3 sets
  1   12 reps
  2   12 reps
  3   12 reps
  note: 5th step

Ring Pull Up                      3 sets
  1   8 reps
  ...
```

A full page. Back button returns to `/workouts`. No modal —
strength detail is scrollable and benefits from real route /
deep-link / shareable URL semantics.

### Treadmill integration

The Active Workout card on Today (currently → `/workout`) is
updated to deep-link to `/workouts/{active_source_id}` instead.
The page detects an active treadmill session and shows the live
controls; otherwise it shows the static detail. The route
`/workout` (singular) becomes a redirect to whichever active
workout is current, or `/workouts` if none.

### More tab

```
More
├─ Workouts        ← new, top of secondary list
├─ Notifications
├─ Settings
└─ ...
```

## Backfill

On first run, the ingestor pages all of `/v1/workouts` (typically
~70 rows for an active user) and writes them through the same
upsert path. No special-case logic — the events cursor starts at
the last `updated_at` seen during backfill.

Override via `HEVY_BACKFILL_DAYS` env var (default: unlimited).
Set to e.g. `30` to only import the last month if the full history
isn't wanted.

## Operational concerns

- **Rate limiting.** Hevy's documented limit is generous (10
  req/sec). The ingestor processes events serially with a small
  jitter. No special handling needed.
- **Webhook registration.** One-time manual step: `POST` to Hevy's
  webhook registration endpoint with the URL and bearer secret.
  Document the curl in `tools/register-hevy-webhook.sh` so it can
  be re-run if the webhook gets nuked.
- **Failure mode: webhook lost.** Cron runs every 6h, catches
  everything since last cursor. Tolerable lag for a strength log.
- **Failure mode: Hevy API down.** Cron retries on next tick; webhook
  events queue in `ingestion_log` and process when service recovers.
  No data loss as long as Hevy itself doesn't lose the workout.
- **Failure mode: stale cursor.** If `ingestion_log` is wiped, cron
  picks up no events; falls back to "process anything updated in
  last N days" via `?updated_since=` if events endpoint allows, else
  re-page the full workout list (idempotent).

## Testing

- **Mappers** (`test_mappers.py`): given a sample Hevy JSON workout,
  produce expected `Workout` row + N `StrengthSet` rows. Cover:
  bodyweight (no `weight_kg`), weighted, timed (planks → `duration_s`),
  superset, dropset, RPE, multi-exercise.
- **Repo** (`test_repo.py`): upsert-then-update flow — first call
  inserts; second call with newer `updated_at` replaces both
  workout and sets; second call with same `updated_at` is a no-op.
  Delete cascade.
- **Runner** (`test_runner.py`): given a stubbed event stream and
  stubbed Hevy client, confirm webhook events and cron events both
  produce the same DB state.
- **Webhook endpoint** (api tests): missing/wrong bearer → 401;
  valid → 204 + `ingestion_log` row written; malformed body → 400.
- **Frontend** (`vitest`): list-view rendering for strength rows;
  detail-view exercise/set rendering; the Today→Active deep-link
  goes to `/workouts/:id`.

## Migration / rollout

1. Land the data model + ingestor + webhook endpoint behind an
   absent `HEVY_API_KEY` (service starts but does nothing). Frontend
   list and detail views ship; strength rows simply don't appear
   yet.
2. Set `HEVY_API_KEY` on `hd`, restart the ingestor → backfill runs.
3. Register the webhook (run `tools/register-hevy-webhook.sh`).
4. Verify: log a workout in Hevy → appears in `/workouts` within
   ~10s (webhook path) and again, no-op, on next cron tick.

No DB migration is required; new fields are additive nullable, new
collection is created on first write.
