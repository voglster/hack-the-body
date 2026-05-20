# Unify Day-Phase into the Coach — Design

**Date:** 2026-05-19
**Status:** Approved for planning

## Problem

The kiosk has two parallel sources of "what time of day is it":

- `services/web/src/lib/dayPhase.ts` — client-side, hardcoded `BEDTIME_HOUR=22, BEDTIME_MIN=45`, defines phases (pre-sunlight / sunlight / movement / wind-down / late) and `windDownMode`. Drives the `KioskPhaseCard` ("WIND DOWN / lights out in 72 min") and hides the coach line during wind-down.
- `services/api/app/services/coach/habits.py` — server-side, hardcoded `BED_CUTOFF_HOUR=22` (10:00 PM). Drives the bedtime habit's done-by cutoff.

These disagree (10:00 PM vs 10:45 PM), and the dayPhase widget bakes in static numbers like "72 min" that don't account for the coach's own time anchors. The user wants a single source of truth and wants the coach to be the voice for time-of-day awareness rather than a separate widget.

## Goals

- One configurable value for lights-out time, read by both the server (habits, coach context) and the kiosk client (palette only).
- The coach becomes the kiosk's voice during wind-down — the dedicated `KioskPhaseCard` and `dayPhase.ts` go away.
- The coach prompt is aware of the current phase and the lights-out anchor, so it can produce sentences like *"Wind down — lights out at {{lights_out}}, that's still on if you start now."*
- The warm/dim wind-down palette stays, but is now driven by the server's `wind_down_mode` flag rather than recomputed client-side.

## Non-Goals

- Multi-phase semantics beyond `day` / `wind-down` / `late`. The old `pre-sunlight` / `sunlight` / `movement` distinctions were labels with no behavior; we drop them.
- Configurable wind-down lead — stays a constant (90 min) until tuning is wanted.
- New automated coach output. We extend the prompt's context; we do not change the brief/kiosk shape or frequency.

## Architecture

### Config

Add to `user_profile.targets`:

- `lights_out_local: str` — `"HH:MM"`, default `"22:00"`.

Reachable through the existing `GET /profile/targets` and `PUT /profile/targets` endpoints (partial PUT already supported per recent fix).

### Server-side phase derivation

New helper `services/api/app/services/coach/phase.py` exporting:

- `WIND_DOWN_LEAD_MIN: int = 90` (constant)
- `compute_phase(now_local: datetime, lights_out_local: str) -> PhaseInfo` returning a dataclass with:
  - `phase: Literal["day", "wind-down", "late"]`
  - `lights_out_at: datetime` (tz-aware, the upcoming lights-out — today's if still ahead, else tomorrow's)
  - `wind_down_mode: bool`

Rules:
- `late` when current local time is **after** today's lights-out and **before** local midnight, OR when after midnight and before the next morning's "day" start (we treat anything from lights-out → 4 AM next day as `late`, then `day`).
- `wind-down` when `lights_out_at - now <= WIND_DOWN_LEAD_MIN`.
- `day` otherwise.
- `wind_down_mode` is `True` for both `wind-down` and `late`.

### Coach context + prompt

`gather_context` (in `brief.py`) gains a `phase` block sourced from `compute_phase`. It is added to the `out` dict passed into the prompt:

```python
out["phase"] = {
    "phase": info.phase,
    "lights_out_at": info.lights_out_at.isoformat(),
    "wind_down_mode": info.wind_down_mode,
}
```

`BRIEF_SYSTEM_PROMPT` and `KIOSK_SYSTEM_PROMPT` gain a short addition: *"`phase` tells you whether it's `day`, `wind-down`, or `late`. During wind-down, your job is to surface the lights-out anchor with `{{lights_out}}` if appropriate. During `late`, acknowledge it without nagging."*

### Kiosk response payload

Both `/coach/insight` and `/coach/kiosk` response payloads gain top-level fields:

- `phase: "day" | "wind-down" | "late"`
- `lights_out_at: ISO string`
- `wind_down_mode: bool`

These come from the same `compute_phase` call. They are *not* persisted on the insight doc — they're transient view-state attached to the response.

### Habits

`services/api/app/services/coach/habits.py::BED_CUTOFF_HOUR` is removed. The bedtime habit's `done`-window check reads `lights_out_local` from the user's targets. (Hours-only granularity is replaced by HH:MM, which is what the config already gives us.)

### Frontend

**Delete:**

- `services/web/src/lib/dayPhase.ts`
- `services/web/src/lib/dayPhase.test.ts`
- `services/web/src/components/kiosk/KioskPhaseCard.tsx`

**Modify:**

- `services/web/src/pages/Kiosk.tsx` — `windDownMode` reads from the kiosk query response (`q.data?.wind_down_mode`), not `phaseInfo`. **Remove** the `!windDownMode && <KioskCoachLine />` hide-during-wind-down behavior — the coach line shows always.
- `services/web/src/components/kiosk/KioskHero.tsx` — the `urgency === "clear"` branch no longer falls back to `<KioskPhaseCard />`. Instead it renders a compact "CLEAR" state or nothing (TBD in plan — likely an empty hero so the coach line carries the screen during clear states).
- `services/web/src/api/types.ts` — `CoachInsight` / `KioskGlance` gain `phase`, `lights_out_at`, `wind_down_mode` as optional fields (server returns them; older clients can ignore).

### Data flow

```
Profile config:        targets.lights_out_local = "22:00"
                                  ↓
Server compute_phase(now_local, "22:00") → {phase, lights_out_at, wind_down_mode}
                       ↓                                          ↓
              gather_context (brief)                        kiosk JSON payload
                       ↓                                          ↓
              Coach prompt sees phase                FE reads phase fields:
              May emit {{lights_out}} anchor          - palette (wind_down_mode)
                       ↓                              - (no separate widget)
              Same anchor system renders live

Bedtime habit: reads targets.lights_out_local for cutoff (replaces hardcoded 22)
```

## Testing

- `compute_phase` unit tests across the day boundary, across the lights-out boundary, with non-default lights-out times.
- `targets` config: PUT/GET round-trip for `lights_out_local`.
- Coach kiosk response: includes `phase`, `lights_out_at`, `wind_down_mode`; matches `compute_phase` output.
- Coach brief response: same fields included.
- Habits: bedtime habit `done`-window uses `lights_out_local` from config.
- FE: `Kiosk.tsx` palette switches based on `q.data?.wind_down_mode`. Coach line renders during wind-down.

## Out of Scope (future)

- Per-day-of-week lights-out (different bedtime on weekends).
- Configurable wind-down lead.
- A scheduled "post-lights-out" auto-summary brief.
