# Food history day navigator + copy-to-today

## Problem

Food often gets eaten before it gets logged. The current food UI on the
Dashboard (`TodayMeals.tsx`) is hard-pinned to today: it fetches today's
entries and totals, and every input ("quick log", paste, usuals) stamps
the current time. There is no way to see what was logged yesterday or
earlier — and no way to re-log a previous day's item against today
(common case: "I forgot to log this pizza two days ago and want it on
today's tally").

## Goal

Let the user walk backward day-by-day from today, see that day's food
log read-only, and copy any individual item or any whole meal section
forward to today.

## Non-goals

- No editing past days. Past entries are read-only in this view (they
  remain editable through the existing entry editor by clicking, but
  see "Edit affordance" below — we are *not* expanding past-day
  editing).
- No calendar picker, no jump-to-date input. Sequential ◀ / ▶ only.
  YAGNI; the use case is "yesterday or a few days back".
- No date in the URL. State is component-local. We don't need shareable
  links to past food days.
- No backend changes. All endpoints already accept a day window.

## UX

`TodayMeals` becomes day-aware. Add a date strip at the top of the
component:

```
  ◀    Tue, Apr 28    [today]
```

- `◀` chevron: shift back one day.
- `▶` chevron: shift forward one day. Disabled when on today.
- Center label: `formatLocalDay(viewedDay)` — e.g. "Tue, Apr 28". When
  on today, the label reads "Today".
- `[today]` jump button: only shown when not on today; one-tap return.
- Hard floor: 30 days back. Beyond that the `◀` is disabled. (Plenty
  for the catch-up use case; keeps query surface small.)

When `viewedDay !== today`:

- The "Quick log", "Paste food", and "My usuals" sections are hidden.
  These are "log now" actions and don't belong on a past-day view.
- The macro stat tiles (cal/protein/carbs/fat) and `MacroProgressCard`
  show that day's totals. (Note: `MacroProgressCard` currently
  hard-codes "today" — see Implementation.)
- Each meal section header gets a `+ copy to today` action button next
  to "save as usual" (which itself is hidden on past days — saving a
  template doesn't depend on the day, but the affordance lives with
  the slot's section either way; hiding keeps the past-day surface
  minimal).
- Each entry row gets a `+ today` button on the right, alongside the
  existing delete `✕`. Tapping copies that single item to today.

When `viewedDay === today` everything behaves exactly as it does now.

### Copy semantics

A copy action re-logs the food via the existing `logEntry` API:

- `food_id`: the original food
- `quantity_g`: the original quantity
- `slot`: **the original slot** (user confirmed: same slot as the
  original — preserves intent; the existing entry editor can fix any
  outliers)
- `ts`: defaults to "now" (server-side, today)
- `note`: not copied (notes are per-occasion)

Water and Vitamins entries are **excluded** from copy actions. They
have dedicated buttons (`WaterCard`, `VitaminsCard`) and copying them
across days would double-count. The `+ today` button simply doesn't
render on rows whose food is "Water" or "Vitamins". The "copy meal to
today" button on a section filters the same way.

After copy, invalidate today's totals + entries queries so the bottom
half of the screen refreshes if the user switches back to today. We
do NOT auto-switch the view back to today — the user is in
"reviewing past day" mode and may want to copy several items.

A subtle confirmation: each row's copy button briefly flashes
"copied ✓" for ~1.2s before reverting. (Same affordance as the
existing "log it" buttons but without leaving the past-day view.)

### Edit affordance on past days

Today, clicking an entry row opens `EntryTimeEditor`. On past days
that still works — the editor lets you adjust `ts` and `slot`, which
is occasionally useful for fixing a mis-logged time. We keep this
behavior; there's no reason to disable it. Delete also remains
available: deleting a past-day mistake is reasonable.

So "read-only" above is slightly imprecise: past days hide the
*logging* surface (quick log / paste / usuals), but per-row edit and
delete still work. What's added is the copy-forward affordance.

## Implementation

### `services/web/src/components/TodayMeals.tsx`

Currently the component owns no day state — it just calls
`api.todayTotals()` / `api.todayEntries()`. We hoist a `viewedDay`
local state (`useState(todayLocalISO())`) and parameterize the API
calls.

The api client's `todayTotals` / `todayEntries` already build their
window from `todayLocalISO()` internally. We add overloads that take
a date string:

```ts
todayTotals: (day?: string) => get(`/meals/today/totals?${dayWindowQuery(day)}`),
todayEntries: (day?: string) => get(`/meals/entries?${dayWindowQuery(day)}`),
```

where `dayWindowQuery(day)` defers to `localDayBoundsUTC(day ?? todayLocalISO())`.
Default behavior (no arg) is unchanged, so callers we don't touch
keep working. Rename `todayWindowQuery` → `dayWindowQuery(day?)` to
make the intent clear; existing callers pass nothing.

React-query keys become `["meals.entries", viewedDay]` and
`["meals.totals", viewedDay]` so each day caches independently. The
mutations (`logTemplate`, `editEntry`, `deleteEntry`) need their
invalidation lists updated to use the predicate form, e.g.
`{ predicate: q => q.queryKey[0] === "meals.entries" }`, since they
should refresh whichever day is being viewed plus today.

### Day strip subcomponent

A small `DayNav` component:

```ts
function DayNav({ day, onChange }: { day: string; onChange: (d: string) => void }) { … }
```

Renders the chevrons + label. `onChange` updates `viewedDay`. Uses
`shiftLocalISO` (already in `lib/tz.ts`) for prev/next. Floors at
"today minus 30" and ceilings at today (≥30 days disables ◀, today
disables ▶).

### Copy actions

Add a `copyEntry` mutation (no API change — it just calls
`api.logEntry({ food_id, quantity_g, slot })` from the source
entry). On success, invalidate today's queries (and only today's —
the past day didn't change). The button's "copied ✓" flash is local
component state on the row.

A "copy meal to today" mutation iterates the saveable entries (same
filter as `templateableEntries` — excludes Water / Vitamins) and fires
a `logEntry` per item. We do them sequentially to keep the order
consistent on the today log; ~5 round trips worst case is fine.

### `MacroProgressCard`

Currently fetches its own `todayTotals` independently. Two options:

a. Lift `MacroProgressCard` to also accept a `day` prop and pass it
   through.
b. Hide `MacroProgressCard` on past days and just show the four stat
   tiles (which already use `totals.data` from the parent query).

I'll go with **(a)**: the card is the most informative readout on
this view and seeing past-day macro adherence is genuinely useful
("how close did I come on Tuesday?"). Small refactor: prop drill
`day` into `MacroProgressCard`, default `undefined` = today.

### Tests

- `services/web/src/lib/__tests__/tz.test.ts` already covers
  `shiftLocalISO` / `localDayBoundsUTC`. No changes there.
- Add a focused unit test for `DayNav`: chevrons disable at the
  bounds, label formats correctly, "today" jump shows only off-today.
- Add a `TodayMeals` smoke test: switching `viewedDay` triggers a new
  fetch with the right window; quick-log/paste/usuals are not
  rendered on a past day; a copy-row button calls `logEntry` with the
  source food's `slot` and `quantity_g`.

No backend tests — the routes already exist and are exercised.

## Risks / open questions

- **Stat tile zeroes on a low-cal past day** can read as "no data"
  when really you ate light. Mitigation: the entry list right below
  is always the source of truth; a near-empty list explains a low
  total. Not worth special UI.
- **Slot mismatch when copying late at night** — if you eat a 11pm
  snack and copy yesterday's "lunch" to it, the copy lands as
  "lunch" on today. User confirmed this is intentional (preserves
  meal intent); if it's wrong, the entry editor fixes it in two
  taps. Not solving here.
- **Timezone travel** — local-day windows already follow the
  browser's TZ, and `shiftLocalISO` works on civil dates, so
  crossing a TZ on a trip just shifts which physical hours the
  "day" covers. Acceptable; this app is local-first.
