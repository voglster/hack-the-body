# Coach Time Anchors + Brief Acknowledgment — Design

**Date:** 2026-05-18
**Status:** Approved for planning

## Problem

Two friction points with the coach output today:

1. **Stale relative time.** The coach writes phrases like "lights out in 53 minutes." Once rendered, the number ages — by the time the user reads it, it's wrong. The browser can compute live offsets if it has the underlying timestamp, but right now the model only emits text.

2. **Repetition across views of the same day.** The user opens the dashboard or kiosk multiple times a day and keeps seeing the same nudge ("hydrate," "watch carbs"). The coach has no signal that the user already read a previous brief, so it cannot deliberately move on. End-of-day reset is sufficient; long-term memory is out of scope.

## Goals

- Browser renders a live, continuously-correct relative time for any time the coach references.
- User can acknowledge a brief from the web app and from the kiosk.
- Acks influence subsequent brief generation on the *same surface* — web acks affect web briefs, kiosk acks affect kiosk briefs.
- Acks reset implicitly at local midnight (no scheduled job).
- An external system (Home Assistant) can ack the latest kiosk brief over HTTP using the existing API key.

## Non-Goals

- Per-insight-card decomposition. Brief remains one message; ack is whole-brief.
- Long-term / cross-day memory, weekly rollups, user-fact stores. Possible later.
- Tracking *who* acked (web user, kiosk tap, HA button). Only the surface matters.

## Architecture

### Time anchors

Coach output gains a structured `anchors` field alongside `text`:

```json
{
  "text": "Lights out at {{lights_out}} — wind-down is still on if you start now.",
  "anchors": { "lights_out": "2026-05-18T22:00:00-05:00" }
}
```

- `text` contains zero or more `{{name}}` placeholders.
- `anchors` is a `dict[str, str]` of placeholder name → ISO-8601 timestamp with timezone offset.
- The set of anchor names is open-ended; the model picks descriptive names (`lights_out`, `next_meal_window`, `workout_start`).
- The prompt forbids relative phrasing ("in N minutes," "soon," "N hours from now"). The model must use a placeholder.

This shape applies to both `/coach/insight` (web brief) and `/coach/kiosk` (kiosk brief). For kiosk, anchors live alongside `verb / qualifier / coach / urgency` in the existing JSON contract.

The `Insight` dataclass in `services/api/app/services/coach/brief.py` gains `anchors: dict[str, str] | None = None`. It is persisted on the insight doc and returned by `_serialize`.

### Frontend rendering

A `useNow(intervalMs=30_000)` hook returns the current `Date` and re-renders subscribers every 30 seconds. A `<CoachText text=... anchors=... />` component:

- Splits `text` on `{{name}}` placeholders.
- For each placeholder, looks up the ISO timestamp and renders a `<RelativeAnchor iso={...} />` child.
- `<RelativeAnchor>` shows the absolute clock time plus a relative chip: e.g. `10:00 PM (in 47m)` — drifting to `(in 46m)` after a tick.
- When the anchor is in the past, it renders `10:00 PM (5m ago)`.

The kiosk reuses the same component. The whole kiosk message body becomes a single `<CoachText>` over the `coach` field.

### Brief acknowledgment

**Data model.** Add `acked_at: datetime | None` to the coach insight document. No new collection. Acked status flows through the existing `recent_insights` query.

**Endpoints** (all under `/coach`, all require API key, same as today):

- `POST /coach/insights/{id}/ack` — acks the named insight. Idempotent: if already acked, returns the existing `acked_at`. Returns `{ "id": ..., "acked_at": ... }`. 404 if the insight does not exist.
- `POST /coach/ack/web-latest` — acks the most recent insight with `trigger=manual` whose `generated_at` is within the caller's local day. Local-day boundaries come from `start` / `end` query params (same convention as `/coach/insight`). Returns `{ "id": ..., "acked_at": ... }` or `{ "id": null, "acked_at": null }` if no eligible insight exists.
- `POST /coach/ack/kiosk-latest` — same as web-latest but filters `trigger=kiosk`. This is the endpoint Home Assistant calls.

**Generation behavior.** `generate_insight` in `brief.py` already pulls `history_snapshot` via `recent_insights(db, since=day_start)`. The history payload that flows into the prompt now includes `acked: bool` per entry. The relevant slice of the prompt is updated to read approximately:

> Some of the messages below have been acknowledged — the user has explicitly marked them as read. Do not restate acked points. You may build on them or surface something the user has not yet seen. Items still unacked may be refined or rephrased if they remain the most important thing right now.

History is already scoped by surface (web briefs see other web briefs because the recent-insights query joins them by trigger context downstream — confirm during implementation; if not, add a `trigger` filter to the history-snapshot path so web and kiosk do not pollute each other).

**Reset.** No scheduled job. Acks from prior days fall out of the `since=day_start` window naturally; each morning's first generation sees an empty history.

### Frontend acknowledgment UI

**Web app.** The coach card gains a single ✓ button. Click → `POST /coach/insights/{id}/ack`. On success the card transitions to an acknowledged visual state: lower opacity, a small "acknowledged Nm ago" footer, and the button hides. State is recovered from `acked_at` on reload — no client-only state.

**Kiosk.** A single tappable affordance (button or full-card tap zone) on the kiosk view. Tap → `POST /coach/ack/kiosk-latest`. The kiosk does not need to know the insight id; "latest" is sufficient since the kiosk only ever shows one brief at a time. After ack, the kiosk shows a brief confirmation state until the next 60-second poll returns either the same insight (now `acked_at`-stamped) or a fresh one.

### Home Assistant integration

No bespoke server-side concept. HA configures a REST command that POSTs to `/coach/ack/kiosk-latest` with the `X-API-Key` header. A physical button (zigbee, etc.) becomes an HA automation that fires that REST command. Documented in the deploy notes; nothing in the API distinguishes HA from a kiosk tap.

## Data Flow

```
User opens web dashboard
  └─ GET /coach/insight?start=...&end=...
     └─ generate_insight(trigger="manual")
        └─ recent_insights(since=day_start) — includes acked flag per entry
        └─ prompt renders "do not restate acked items"
     └─ returns { text, anchors, id, acked_at: null, ... }
  └─ <CoachText> renders text with live <RelativeAnchor> children
  └─ User clicks ✓
     └─ POST /coach/insights/{id}/ack
     └─ acked_at written
     └─ card transitions to acknowledged state

Home Assistant button press
  └─ HA REST command → POST /coach/ack/kiosk-latest
  └─ Server finds latest trigger=kiosk insight in today's window
  └─ Sets acked_at if unset
  └─ Kiosk's next 60s poll renders acknowledged state
```

## Testing

- **Anchors round-trip.** Unit test for the brief serializer: insight with anchors persists and `_serialize` returns them.
- **Prompt contract.** Test that the system prompt contains the "never write 'in N minutes'" rule and the anchors-format example.
- **Ack idempotency.** Acking the same insight twice does not overwrite `acked_at`.
- **Ack by surface.** `web-latest` ignores kiosk insights and vice versa.
- **Ack scoped to local day.** An insight from yesterday cannot be acked by `*-latest` when today's window is passed.
- **History reflects acks.** After acking an insight, `recent_insights` for that surface returns it with `acked=true`.
- **FE: `<RelativeAnchor>`** unit tests with `useNow` mocked — absolute past, near future, far future, midnight crossing.
- **FE: ack flow** — clicking the button calls the endpoint, the card transitions, reload preserves the state from `acked_at`.

## Open Questions Deferred to Implementation

- Whether `recent_insights` already filters by trigger when called from `generate_insight`, or whether we need to add that filter so web/kiosk history streams stay independent. (Likely a small change in `brief.py`.)
- Exact visual treatment of the acknowledged state — settle in implementation with a quick screenshot check.

## Out of Scope (Future Work)

- Long-term memory: user facts, weekly rollups, semantic recall across days.
- Per-card insight decomposition.
- Notifying the FE in realtime when an external (HA) ack lands — current 60s kiosk poll is sufficient.
