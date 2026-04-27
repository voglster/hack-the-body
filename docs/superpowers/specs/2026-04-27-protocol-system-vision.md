---
status: vision
created: 2026-04-27
---

# Protocol System — Long-Range Vision

## The reframe

What looks like a health app is actually a **protocol management system for a
human**. Vitamins, water, sleep, workouts are the current focus, but the same
shape applies to:

- Practicing bass guitar
- Hanging out with the kids
- Reading / learning
- Meditation
- Anything the user wants to be more deliberate about

A "protocol" is: a target behavior, a cadence, a way to detect adherence, and
optionally a coach loop that helps the user stay on it. The system reminds,
schedules, observes, and (eventually) adapts.

## Implication for current specs

- Data model and rules engine should be **generic over protocol type**, not
  health-specific. Avoid hardcoded names like "vitamin_nudge"; prefer
  `protocol_id` / `protocol_kind` so non-health protocols slot in later.
- v1 ships health protocols only — but the schema and code paths must not
  assume health is the only domain.
- The Sleep Accountability Loop spec generalizes: replace "sleep" with any
  protocol that has a measurable adherence signal.

## Future workout-related notes

- User uses **Hevy** (has an API) for strength workouts. Garmin captures
  cardio. Future ingestor: pull Hevy sessions into the same workout surface.
- Coach should eventually **schedule** workouts (and other protocols), not
  just react to them. That's a separate future spec.

## Predictive nudging (future)

Once a protocol has enough history, the system should learn the user's
*typical* adherence pattern and fire earlier when current behavior diverges
from it. Example: "you usually take vitamins by 9am; it's 10am and you
haven't — you tend to skip on days you miss this window." This converts
nudges from threshold-based to pattern-based, and is a natural extension of
the rules engine once a per-protocol history table exists.

## Not in scope yet

Anything non-physical. But every design decision in the current physical-only
specs should be reviewed through the lens of "would this make it harder to
add a bass-practice protocol later?"
