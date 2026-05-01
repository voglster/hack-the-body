# Treadmill Tracker — Design

## Goal

Capture treadmill workouts automatically: when the user turns the
Precor on (via Alexa/HA smart plug), record speed, grade, distance,
HR, etc. for the duration of the walk. When they turn it off,
finalize the session. Long-term enables a realtime coach that
suggests speed/grade adjustments to keep HR in target zones.

## Architecture

Two pieces, following the existing `ingestor-garmin` pattern:

1. **`services/treadmill-tracker`** — new Docker container, runs on
   `hd` (LAN access to the bridge). Dumb relay: maintains one TCP
   connection to `treadmill-bridge.local:8023`, polls CSAFE, writes
   raw samples to Mongo. No session logic.

2. **HTB API (`services/api`)** — adds endpoints that read the raw
   samples, detect sessions, aggregate finished workouts, and serve
   active-workout state to the frontend. Session detection lives
   here so the relay stays restart-safe and rewritable.

```
[Precor] -CSAFE/RS232- [ESP8266 bridge :8023]
                              ↑ TCP
                    [treadmill-tracker]
                              ↓ writes
                          [Mongo]
                              ↑ reads
                       [HTB API /workouts/*]
                              ↑ HTTP
                          [Web/Kiosk]
```

## Relay polling state machine

The bridge accepts TCP connections even when the treadmill is off,
but CSAFE responses time out. The relay uses two modes:

- **Idle** — single `GETSTATUS` (0x80) probe every 15s with a 200ms
  read timeout. Cheap; blocks only on real treadmill-off case.
- **Active** — full 7-command sweep at 2 Hz with 600ms timeouts.
  Writes one sample doc per sweep.

**Transitions:**

- Idle → Active: one successful probe response.
- Active → Idle: 3 consecutive sweep failures (~3s of silence).

Bench results (2026-05-01, walking 1mph):

| command       | mean   | p95    |
|---------------|--------|--------|
| GETSTATUS     | 16ms   | 25ms   |
| GETSPEED      | 22ms   | 26ms   |
| GETGRADE      | 23ms   | 34ms   |
| GETHORIZONTAL | 21ms   | 28ms   |
| GETCALORIES   | 21ms   | 26ms   |
| GETTWORK      | 22ms   | 26ms   |
| GETHRCUR      | 21ms   | 25ms   |

Full sweep mean 289ms, p95 307ms → 2 Hz comfortable, 3 Hz feasible.
Zero misses across 30 samples per command.

## Data model

### `treadmill_samples` (time-series, written by relay)

Mongo time-series collection, `metaField: "source"`, `timeField: "ts"`,
`granularity: "seconds"`. TTL: **90 days**.

```json
{
  "ts":           "2026-05-01T17:32:14.412Z",
  "source":       "precor-csafe",
  "speed_mph":    3.2,
  "grade_pct":    1.5,
  "distance_raw": 1234,
  "calories":     45,
  "twork_s":      612,
  "hr_bpm":       128,
  "state":        9
}
```

Notes:
- `state` is the bottom nibble of the CSAFE GETSTATUS payload. On
  this Precor it sits at `0x09` ("Manual/Local") whenever the user
  is driving — not useful for session boundaries on its own.
  Captured for diagnostics.
- `distance_raw` is the raw 16-bit CSAFE counter from
  `GETHORIZONTAL`. **Calibrated 2026-05-01: 1 count = 0.001 mi**
  (Precor deviates from the CSAFE 1.5 "0.001 km" spec — it uses
  the same numeric unit but in miles, matching the on-deck
  display). Aggregator: `distance_mi = (end_raw - start_raw) * 0.001`,
  with u16 wraparound handling at 65535 (≈65 mi per session, fine).
- HR is `0` when the strap isn't paired — aggregator filters those.

Dedup: relay writes one doc per sweep, no need for source_id; the
aggregator can tolerate duplicate timestamps if the relay restarts
mid-second.

### `workouts` (one doc per session, written by aggregator)

Regular collection, kept **forever**.

```json
{
  "_id":          ObjectId,
  "started_at":   "2026-05-01T17:30:00Z",
  "ended_at":     "2026-05-01T18:05:12Z",
  "duration_s":   2112,
  "active_s":     1980,            // samples where speed > 0
  "distance_mi":  1.42,
  "avg_speed":    2.6,
  "max_speed":    3.5,
  "avg_grade":    1.2,
  "max_grade":    4.0,
  "avg_hr":       118,
  "max_hr":       142,
  "hr_zones_s": { "z1": 600, "z2": 1100, "z3": 280, "z4": 0, "z5": 0 },
  "calories":     180,
  "sample_count": 4224,
  "status":       "complete"       // "active" | "complete"
}
```

While the session is in progress, a doc with `status: "active"` is
*not* persisted on every change — it's computed on demand from raw
samples. On session close (first request that finds the gap) the
finalized `complete` doc is written.

## Session detection (in HTB API)

**Pull-on-read.** No background task. Session state is computed
from raw samples whenever the API is asked:

- `GET /workouts/active` queries the most recent sample. If `ts` is
  within the last 30s, build the active aggregate from samples
  since the last gap > 30s and return it (status: `active`).
- If the most recent sample is older than 30s but no `complete`
  workout doc exists for that span, finalize the session: aggregate
  samples from session-start to last-sample, write a `complete`
  doc, return that.
- If everything is finalized and quiet, return 204.

The 30s window is generous: relay idle-probe interval is 15s, and a
real treadmill-off produces a gap > 15s within one or two probes.

This avoids any background-task lifecycle worries and means the
"live" view is always current as of the latest sample, never stale.
For 15-60 minute walks, the cost of recomputing from raw samples on
each request is trivial (~3000-7000 docs in a time-series scan).

HR zone math uses static thresholds for now (configurable later):
- Z1 < 110, Z2 110-129, Z3 130-149, Z4 150-169, Z5 ≥ 170.

## API endpoints

Added to `services/api/app/`:

- `GET /workouts/active` → current active workout doc, or 204 if none.
- `GET /workouts?limit=N&since=...` → recent completed workouts.
- `GET /workouts/{id}` → one workout with full aggregates.
- `GET /workouts/{id}/samples` → raw samples for that session
  (charting on the frontend).

These follow the existing auth + `/config.js` pattern.

## Deployment

Add `treadmill-tracker` to:

- `services/treadmill-tracker/Dockerfile` (Python 3.12-slim, uv install)
- `.github/workflows/build.yml` builds + pushes
  `ghcr.io/voglster/hack-the-body-tracker-treadmill`
- `compose/docker-compose.yml` adds the new service. Same `.env`
  loads `MONGO_URL`. New env: `BRIDGE_HOST=treadmill-bridge.local`,
  `BRIDGE_PORT=8023`.
- Watchtower command list on `hd` adds `hack-the-body-tracker-treadmill`.

The relay must run on `hd` (LAN access to the ESP). Other HTB
services can run anywhere; this one is host-pinned by network
locality.

## Out of scope (future)

- **Realtime coach** — Phase-2 Telegram/voice loop reads
  `/workouts/active` and the live samples stream, decides "bump to
  3.5 mph" / "drop grade by 1%", and announces over TTS. Hooks for
  this exist via the active-workout endpoint; coach service is
  separate.
- **HA notifications** — push events to HA so dashboards/automations
  can react ("workout started", "missed strap"). Trivial to add
  later; HTB writes to a webhook URL.
- **"You forgot the strap" nudge** — relay sees treadmill on but
  HR=0 for 60s → ping user. Low priority.
- **Other CSAFE devices** — bike, rower. Same bridge, same pattern;
  separate relay instance per device.

## Testing

- Relay: unit tests for the polling state machine (mode transitions,
  probe vs sweep selection) using a fake socket. Integration test
  against a recorded CSAFE byte stream.
- API: tests for session detection (synthetic samples in fixture
  Mongo) and aggregate math (HR zones, distance, active time).
- E2E manual: walk for 5 min, verify the workout shows up in
  `/workouts` with sane numbers.
