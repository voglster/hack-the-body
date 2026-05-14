# Kiosk Redesign — Action-First Glance Display

**Date:** 2026-05-14
**Owner:** Jim
**Status:** Draft

## Why

The current kiosk (Pi behind the office desk, glanced at when walking
out of the room) shows four recovery tiles: Weight, Sleep, HRV, VO2
Max. They're nice numbers but **inert** — none of them answer the
question "do I need to do something right now?"

A kiosk you glance at on the way out is a near-perfect *prompt*
surface (Fogg behavior model: behavior = motivation + ability +
prompt). The redesign reorganizes the screen around **time-sensitive,
actionable state** — am I on pace for steps, have I eaten, did I take
vitamins, have I weighed in — and demotes static recovery metrics to
a single bottom strip.

## What changes

### Layout (Kiosk.tsx)

```
┌──────────────────────────────────────────────────────────────────┐
│ 3:42 PM   Thursday, May 14                       ● synced 2m ago │
├──────────────────────────────────────────────────────────────────┤
│ 🧠  You're behind on steps and haven't logged lunch.             │
│     A 15-min walk now puts you back on pace.                     │
├────────────────────────────┬─────────────────────────────────────┤
│ STEPS                      │  💊 Vitamins      ✓                 │
│  6,420  / 10,000           │  ⚖️  Weigh in      ! today           │
│  ████████░░░░  64%         │  🍽  Last meal    9:14 am           │
│  on pace · 720/hr to goal  │  💧 Water         42 / 80 oz        │
├────────────────────────────┴─────────────────────────────────────┤
│  Sleep 7h24m ★82   HRV 68ms   RHR 54   Weight 182.4   VO2 47.2   │
└──────────────────────────────────────────────────────────────────┘
```

Four zones, in order of glance priority:

1. **Header** (small) — clock, date, sync-age dot. Existing
   `SyncStatusFooter` logic can be reused inline.
2. **Coach line** (large, top-attention) — one or two sentences from
   the new `/coach/kiosk` endpoint. ~3xl text. Falls back to a
   client-side deterministic line ("Behind on steps · lunch not
   logged") if the endpoint is unavailable or returns nothing fresh.
3. **Action row** (hero, two columns) —
   - Left: Steps progress. Big count, ratio of goal, progress bar with
     a *where I should be by now* marker, plain-English pace status
     line. Reuse the math in `StepsTodayCard` (`expectedFractionAt`,
     `forecast`) — extract it into `lib/stepsForecast.ts` so both the
     dashboard card and the kiosk hero share one source of truth.
   - Right: Today checklist — four rows, each one icon + label +
     status. Status glyphs:
     - ✓ done (green)
     - ! attention needed (amber)
     - dim text "—" when neutral/not-yet-due
   Items:
     - **Vitamins** — `/vitamins/today` `.logged`. ✓ when logged.
       Amber after 10:00 local if not.
     - **Weigh in** — `summary.weight.ts` falls on today's local
       date → ✓. Amber after 09:00 local if missing.
     - **Last meal** — derived from `/meals/entries` for today.
       Shows "h:mm a" of latest entry; amber if >5h ago and local
       time is between 11:00 and 21:00; "—" before 09:00.
     - **Water** — `/water/today.oz` over user target (from
       `/profile/targets.daily_water_oz` if set, else 80). Amber if
       fraction is more than 0.20 below `expectedFractionAt(now)`.
4. **Recovery strip** (bottom, small, single line) — Sleep
   duration+score, HRV, RHR, Weight, VO2 Max. Same data the kiosk
   already shows, just compressed.

### `/coach/kiosk` endpoint (new)

A dedicated short-form coach endpoint, structurally parallel to
`/coach/insight`. Lives in `services/api/app/routers/coach.py`.

**Request:** `GET /coach/kiosk?start=<utc>&end=<utc>`
(same local-day-window pattern as `/coach/insight`.)

**Response:** the existing `CoachInsight` shape (so the FE can reuse
types), with `text` constrained to ≤160 chars / 1-2 sentences.

**Server-side caching:** the kiosk polls every 60s; we don't want to
hit the LLM that often. Cache the result in `app.state` keyed by the
local-day window, TTL 15 min. After TTL, the next request
regenerates. Cache invalidates on day boundary.

**Prompt:** introduce a `KIOSK_SYSTEM_PROMPT` in
`services/api/app/services/coach/brief.py` (alongside the existing
`SYSTEM_PROMPT`). The kiosk prompt asks for: present tense, one or
two short sentences, ≤160 chars total, lead with the highest-leverage
*action* available right now. No greetings, no sign-offs, no
emoji. Context payload is identical to `/coach/insight`.

`generate_insight` already takes a `system_prompt` parameter; the
kiosk endpoint passes `KIOSK_SYSTEM_PROMPT` and `trigger="kiosk"` so
feedback / debugging tooling can filter on it.

### FE wiring

- `services/web/src/api/client.ts`: add `api.coachKiosk()` returning
  `CoachInsight`.
- `services/web/src/pages/Kiosk.tsx`: rewrite to the layout above.
  Hooks:
  - `useQuery(["summary"])` — already there, 5 min interval.
  - `useQuery(["steps-today"])` → `api.stepsDay(start, end)`, 60 s
    interval.
  - `useQuery(["coach-kiosk"])` → `api.coachKiosk()`, 5 min interval
    (server cache handles the rest).
  - `useQuery(["vitamins-today"])`, `useQuery(["water-today"])`,
    `useQuery(["today-entries"])` — 60 s interval each.
- Extract `lib/stepsForecast.ts` from `StepsTodayCard.tsx`. Both the
  card and the kiosk import from there. Keep the existing card's
  rendering; only the math moves.
- New components, kept small and focused:
  - `components/kiosk/KioskCoachLine.tsx` — coach text + fallback.
  - `components/kiosk/KioskStepsHero.tsx` — big steps panel.
  - `components/kiosk/KioskChecklist.tsx` — 4-row status list.
  - `components/kiosk/KioskRecoveryStrip.tsx` — bottom single line.

## Out of scope

- Coach-line interactivity (tap to expand) — kiosk is read-only.
- Touch input on the Pi screen. The Pi is HDMI-only behind the desk.
- New data sources. Everything renders from existing endpoints
  (+ the new `/coach/kiosk` which reuses existing context).
- Updates to the dashboard view itself. This change only affects
  `/kiosk`.

## Testing

- Unit: `lib/stepsForecast.test.ts` for the extracted forecast math
  (covers what `StepsTodayCard` currently expects).
- Unit: `KioskChecklist.test.tsx` — verifies status glyph for each
  of the four rows under early-morning, mid-day, and late-evening
  fake clocks.
- API: `tests/test_coach_kiosk.py` — endpoint returns a kiosk-shaped
  insight, second call within TTL returns the cached object (assert
  same `id`), call after window change regenerates.
- Manual: open `http://hd:8080/kiosk` after deploy, confirm at three
  times of day (morning before vitamins, mid-day with checklist
  half-done, evening with everything done).
