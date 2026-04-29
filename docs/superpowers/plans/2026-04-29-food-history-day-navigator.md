# Food History Day Navigator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `TodayMeals` day-aware so the user can walk back through previous days' food logs and copy items (per-row or per-meal) to today.

**Architecture:** Frontend-only. `TodayMeals` owns a local `viewedDay` state. The api client's window helpers gain an optional `day` parameter; existing callers (passing nothing) keep today behavior. A small `DayNav` component owns chevron-strip UI. Past-day mode hides logging affordances and surfaces copy-to-today actions that re-call `logEntry` with the source row's `food_id`/`quantity_g`/`slot`.

**Tech Stack:** React + TanStack Query + Vitest + Testing Library, existing `lib/tz.ts` helpers.

---

## File Structure

- Modify `services/web/src/api/client.ts` — generalize `todayWindowQuery` → `dayWindowQuery(day?)`; thread optional `day` through `todayTotals` / `todayEntries`.
- Create `services/web/src/components/DayNav.tsx` — `◀ label ▶ [today]` strip.
- Create `services/web/src/components/DayNav.test.tsx` — chevron disabled-states + jump-to-today behavior.
- Modify `services/web/src/components/MacroProgressCard.tsx` — accept optional `day` prop.
- Modify `services/web/src/components/TodayMeals.tsx` — own `viewedDay`, render `DayNav`, hide logging surface on past days, add copy actions.

---

### Task 1: Parameterize the api client window helpers

**Files:**
- Modify: `services/web/src/api/client.ts`

- [ ] **Step 1: Replace `todayWindowQuery` with `dayWindowQuery`**

In `services/web/src/api/client.ts`, replace:

```ts
function todayWindowQuery(): string {
  const { start, end } = localDayBoundsUTC(todayLocalISO());
  return `start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
}
```

with:

```ts
function dayWindowQuery(day?: string): string {
  const { start, end } = localDayBoundsUTC(day ?? todayLocalISO());
  return `start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`;
}
```

- [ ] **Step 2: Update `todayTotals` and `todayEntries` to accept an optional day**

Change the two methods on the `api` object:

```ts
todayTotals: (day?: string) => get<TodayTotals>(`/meals/today/totals?${dayWindowQuery(day)}`),
todayEntries: (day?: string) => get<MealEntry[]>(`/meals/entries?${dayWindowQuery(day)}`),
```

- [ ] **Step 3: Update remaining callers of the renamed helper**

Replace every `todayWindowQuery()` call in this file with `dayWindowQuery()` (no-arg behaves the same). Affected lines: `coachInsight`, `waterToday`, `vitaminsToday`. Verify with:

```bash
rg "todayWindowQuery" services/web/src
```

Expected: no matches.

- [ ] **Step 4: Typecheck + tests**

Run:

```bash
cd services/web && npm run typecheck && npm test -- --run
```

Expected: passes (no behavioral change yet).

- [ ] **Step 5: Commit**

```bash
git add services/web/src/api/client.ts
git commit -m "refactor(web): parameterize day window helpers for past-day fetching"
```

---

### Task 2: DayNav component (TDD)

**Files:**
- Create: `services/web/src/components/DayNav.tsx`
- Create: `services/web/src/components/DayNav.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `services/web/src/components/DayNav.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DayNav } from "./DayNav";
import { todayLocalISO, shiftLocalISO } from "../lib/tz";

describe("DayNav", () => {
  it("shows 'Today' label and disables forward chevron when on today", () => {
    const onChange = vi.fn();
    render(<DayNav day={todayLocalISO()} onChange={onChange} />);
    expect(screen.getByText("Today")).toBeTruthy();
    expect(screen.getByLabelText("next day").hasAttribute("disabled")).toBe(true);
    expect(screen.queryByRole("button", { name: "jump to today" })).toBeNull();
  });

  it("calls onChange with previous day when ◀ clicked", () => {
    const today = todayLocalISO();
    const onChange = vi.fn();
    render(<DayNav day={today} onChange={onChange} />);
    fireEvent.click(screen.getByLabelText("previous day"));
    expect(onChange).toHaveBeenCalledWith(shiftLocalISO(today, -1));
  });

  it("disables ◀ at the 30-day floor", () => {
    const floor = shiftLocalISO(todayLocalISO(), -30);
    render(<DayNav day={floor} onChange={vi.fn()} />);
    expect(screen.getByLabelText("previous day").hasAttribute("disabled")).toBe(true);
  });

  it("shows the today jump button on past days and uses it", () => {
    const today = todayLocalISO();
    const yesterday = shiftLocalISO(today, -1);
    const onChange = vi.fn();
    render(<DayNav day={yesterday} onChange={onChange} />);
    fireEvent.click(screen.getByRole("button", { name: "jump to today" }));
    expect(onChange).toHaveBeenCalledWith(today);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
cd services/web && npm test -- --run DayNav
```

Expected: FAIL — module not found.

- [ ] **Step 3: Implement DayNav**

Create `services/web/src/components/DayNav.tsx`:

```tsx
import { formatLocalDay, shiftLocalISO, todayLocalISO } from "../lib/tz";

const FLOOR_DAYS = 30;

export function DayNav({ day, onChange }: { day: string; onChange: (d: string) => void }) {
  const today = todayLocalISO();
  const floor = shiftLocalISO(today, -FLOOR_DAYS);
  const atToday = day === today;
  const atFloor = day === floor || day < floor;
  const label = atToday ? "Today" : formatLocalDay(day);

  return (
    <div className="flex items-center justify-between gap-2 mb-2">
      <button
        onClick={() => onChange(shiftLocalISO(day, -1))}
        disabled={atFloor}
        aria-label="previous day"
        className="px-3 py-2 min-h-[44px] min-w-[44px] text-neutral-300 active:text-white disabled:opacity-30"
      >
        ◀
      </button>
      <div className="flex-1 text-center text-sm font-medium text-neutral-200 tabular-nums">
        {label}
      </div>
      {!atToday && (
        <button
          onClick={() => onChange(today)}
          aria-label="jump to today"
          className="px-3 py-2 min-h-[44px] text-xs uppercase tracking-wide text-emerald-300 active:text-emerald-200"
        >
          today
        </button>
      )}
      <button
        onClick={() => onChange(shiftLocalISO(day, 1))}
        disabled={atToday}
        aria-label="next day"
        className="px-3 py-2 min-h-[44px] min-w-[44px] text-neutral-300 active:text-white disabled:opacity-30"
      >
        ▶
      </button>
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
cd services/web && npm test -- --run DayNav
```

Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add services/web/src/components/DayNav.tsx services/web/src/components/DayNav.test.tsx
git commit -m "feat(web): add DayNav chevron strip for food history navigation"
```

---

### Task 3: Thread `day` prop through MacroProgressCard

**Files:**
- Modify: `services/web/src/components/MacroProgressCard.tsx`

- [ ] **Step 1: Accept an optional `day` prop and pass it through the query**

Change the component signature and query in `MacroProgressCard.tsx`. Find the existing query block:

```tsx
const totals = useQuery({
  queryKey: ["meals.today.totals"],
  queryFn: api.todayTotals,
  ...
});
```

and the component definition. Update so the component accepts `day?: string` and the query is keyed/parameterized on it:

```tsx
export function MacroProgressCard({ day }: { day?: string } = {}) {
  // ... existing code, then:
  const totals = useQuery({
    queryKey: ["meals.totals", day ?? "today"],
    queryFn: () => api.todayTotals(day),
    refetchInterval: 60_000,
  });
  // ... rest unchanged
}
```

If the "Today" header label inside the card is hard-coded (line ~158), leave it alone — it reads "Today" but on past-day view the outer `DayNav` already shows the date. Acceptable for v1.

- [ ] **Step 2: Typecheck + tests**

```bash
cd services/web && npm run typecheck && npm test -- --run
```

Expected: passes.

- [ ] **Step 3: Commit**

```bash
git add services/web/src/components/MacroProgressCard.tsx
git commit -m "refactor(web): MacroProgressCard accepts optional day prop"
```

---

### Task 4: Wire `viewedDay` state into TodayMeals

**Files:**
- Modify: `services/web/src/components/TodayMeals.tsx`

- [ ] **Step 1: Add viewedDay state and parameterize the day-scoped queries**

At the top of `TodayMeals` (just after `const qc = useQueryClient()`), add:

```tsx
import { todayLocalISO } from "../lib/tz";
import { DayNav } from "./DayNav";

// ...

const [viewedDay, setViewedDay] = useState<string>(todayLocalISO());
const isToday = viewedDay === todayLocalISO();
```

(The existing `useState` import is already present.) Update the totals + entries queries to be day-scoped:

```tsx
const totals = useQuery({
  queryKey: ["meals.totals", viewedDay],
  queryFn: () => api.todayTotals(viewedDay),
  refetchInterval: 60_000,
});
const entries = useQuery({
  queryKey: ["meals.entries", viewedDay],
  queryFn: () => api.todayEntries(viewedDay),
  refetchInterval: 60_000,
});
```

- [ ] **Step 2: Update mutation invalidations to refresh the active day plus today**

The existing `refresh` helper invalidates by hard-coded keys. Replace it with:

```tsx
const refresh = () => {
  void qc.invalidateQueries({ predicate: q => {
    const k = q.queryKey[0];
    return k === "meals.totals" || k === "meals.entries";
  }});
};
```

That covers any cached day; cheap given there's at most a handful.

- [ ] **Step 3: Render DayNav at the top, MacroProgressCard with the day**

Replace the component's outer JSX, just inside the `space-y-4 sm:space-y-6` wrapper. Before the `<MacroProgressCard />` line, insert:

```tsx
<DayNav day={viewedDay} onChange={setViewedDay} />
```

and update the `<MacroProgressCard />` line to:

```tsx
<MacroProgressCard day={isToday ? undefined : viewedDay} />
```

- [ ] **Step 4: Hide logging surface on past days**

Wrap the "My usuals" block, `<PasteFood>`, and `<QuickLog>` in `{isToday && (...)}`. Each becomes:

```tsx
{isToday && templates.data && templates.data.length > 0 && (
  <div>
    {/* existing usuals block */}
  </div>
)}
{isToday && <PasteFood onLogged={refresh} />}
{isToday && <QuickLog onLogged={refresh} />}
```

- [ ] **Step 5: Update the entry-list header label**

In `EntryList`, the "Today's log" header is hard-coded. Add a prop and use it. Change the signature:

```tsx
function EntryList({ entries, onDelete, onEdit, onSaveSlotAsUsual, savingUsual, isToday, onCopyEntry, onCopyMeal, copying }: {
  entries: MealEntry[] | undefined;
  onDelete: (id: string) => void;
  onEdit: (id: string) => void;
  onSaveSlotAsUsual: (slot: MealSlot, list: MealEntry[], name: string) => void;
  savingUsual: boolean;
  isToday: boolean;
  onCopyEntry: (e: MealEntry) => void;
  onCopyMeal: (list: MealEntry[]) => void;
  copying: boolean;
}) {
```

(Implementation of `onCopyEntry` / `onCopyMeal` arrives in Task 5; for this task, just plumb them as `() => {}` placeholders from the parent so the file typechecks.)

Replace the two header strings:

```tsx
const header = isToday ? "Today’s log" : "Day log";
// empty state:
<div className="text-sm text-neutral-500">
  {isToday ? "nothing logged yet" : "nothing logged this day"}
</div>
// populated header line:
<div className="text-xs uppercase tracking-wide text-neutral-500">
  {header} ({entries.length})
</div>
```

In the parent (`TodayMeals`), update the `<EntryList ... />` props:

```tsx
<EntryList
  entries={entries.data}
  onDelete={(id) => deleteEntry.mutate(id)}
  onEdit={setEditingId}
  onSaveSlotAsUsual={saveSlotAsUsual}
  savingUsual={createTemplate.isPending}
  isToday={isToday}
  onCopyEntry={() => {}}
  onCopyMeal={() => {}}
  copying={false}
/>
```

`onCopyEntry` / `onCopyMeal` / `copying` get filled in Task 5.

- [ ] **Step 6: Typecheck + tests**

```bash
cd services/web && npm run typecheck && npm test -- --run
```

Expected: passes (visual change only on dashboard; existing tests untouched).

- [ ] **Step 7: Manual smoke**

```bash
cd services/web && npm run dev
```

Open the dashboard, scroll to the food card. Confirm:
- DayNav strip is visible above macros.
- Clicking ◀ shifts the label to yesterday's date.
- Quick log, paste, and usuals disappear when on a past day.
- Clicking ▶ or "today" returns you to today and the logging surface returns.

- [ ] **Step 8: Commit**

```bash
git add services/web/src/components/TodayMeals.tsx
git commit -m "feat(web): day-aware TodayMeals with DayNav and past-day read mode"
```

---

### Task 5: Copy-to-today actions

**Files:**
- Modify: `services/web/src/components/TodayMeals.tsx`

- [ ] **Step 1: Add the copy mutations in TodayMeals**

Inside `TodayMeals`, alongside the other mutations, add:

```tsx
const copyOneToToday = useMutation({
  mutationFn: (e: MealEntry) =>
    api.logEntry({ food_id: e.food_id, quantity_g: e.quantity_g, slot: e.slot }),
  onSuccess: refresh,
});

const copyMealToToday = useMutation({
  mutationFn: async (list: MealEntry[]) => {
    for (const e of list) {
      await api.logEntry({ food_id: e.food_id, quantity_g: e.quantity_g, slot: e.slot });
    }
  },
  onSuccess: refresh,
});
```

- [ ] **Step 2: Wire mutations through to EntryList**

Replace the placeholder props on `<EntryList ... />` with the real ones:

```tsx
onCopyEntry={(e) => copyOneToToday.mutate(e)}
onCopyMeal={(list) => copyMealToToday.mutate(list)}
copying={copyOneToToday.isPending || copyMealToToday.isPending}
```

- [ ] **Step 3: Plumb props down through SlotSection and EntryRow**

Update `SlotSection`'s prop type to include the copy props and `isToday`:

```tsx
function SlotSection({ slot, list, onDelete, onEdit, onSaveAsUsual, savingUsual, isToday, onCopyEntry, onCopyMeal, copying }: {
  slot: MealSlot;
  list: MealEntry[];
  onDelete: (id: string) => void;
  onEdit: (id: string) => void;
  onSaveAsUsual: (slot: MealSlot, list: MealEntry[], name: string) => void;
  savingUsual: boolean;
  isToday: boolean;
  onCopyEntry: (e: MealEntry) => void;
  onCopyMeal: (list: MealEntry[]) => void;
  copying: boolean;
}) {
```

In `SlotSection`, replace the existing right-aligned action area in the section header:

```tsx
{!naming && isToday && saveable.length > 0 && (
  <button
    onClick={beginNaming}
    className="text-[11px] text-neutral-500 active:text-emerald-300 px-1"
    aria-label={`save ${SLOT_LABEL[slot]} as a usual`}
  >
    + save as usual
  </button>
)}
{!isToday && saveable.length > 0 && (
  <button
    onClick={() => onCopyMeal(saveable)}
    disabled={copying}
    className="text-[11px] text-neutral-500 active:text-emerald-300 px-1 disabled:opacity-50"
    aria-label={`copy ${SLOT_LABEL[slot]} to today`}
  >
    + copy to today
  </button>
)}
```

In `EntryList`, pass the props down:

```tsx
{visibleSlots.map(slot => (
  <SlotSection
    key={slot}
    slot={slot}
    list={grouped.get(slot) ?? []}
    onDelete={onDelete}
    onEdit={onEdit}
    onSaveAsUsual={onSaveSlotAsUsual}
    savingUsual={savingUsual}
    isToday={isToday}
    onCopyEntry={onCopyEntry}
    onCopyMeal={onCopyMeal}
    copying={copying}
  />
))}
```

In `SlotSection`, update the `<EntryRow .../>` mapping:

```tsx
{list.map(e => (
  <EntryRow
    key={e.id}
    entry={e}
    onDelete={onDelete}
    onEdit={onEdit}
    showCopy={!isToday && !TEMPLATE_EXCLUDED_NAMES.has(e.food_name)}
    onCopy={() => onCopyEntry(e)}
    copying={copying}
  />
))}
```

Update `EntryRow`:

```tsx
function EntryRow({ entry: e, onDelete, onEdit, showCopy, onCopy, copying }: {
  entry: MealEntry;
  onDelete: (id: string) => void;
  onEdit: (id: string) => void;
  showCopy: boolean;
  onCopy: () => void;
  copying: boolean;
}) {
  const [flashed, setFlashed] = useState(false);
  const cal = e.macros.calories ? `${Math.round(e.macros.calories)} cal` : "";
  const protein = e.macros.protein_g ? `${Math.round(e.macros.protein_g)} p` : "";
  const detailParts = [
    fmtClock(e.ts), `${Math.round(e.quantity_g)}g`, cal, protein,
  ].filter(Boolean);
  const handleCopy = () => {
    onCopy();
    setFlashed(true);
    setTimeout(() => setFlashed(false), 1200);
  };
  return (
    <li className="py-3 flex justify-between gap-3 items-center">
      <button
        onClick={() => onEdit(e.id)}
        className="min-w-0 flex-1 text-left active:bg-neutral-800/50 -mx-1 px-1 rounded"
        aria-label={`edit time of ${e.food_name}`}
      >
        <div className="font-medium truncate">{e.food_name}</div>
        <div className="text-xs text-neutral-500">{detailParts.join(" · ")}</div>
      </button>
      {showCopy && (
        <button
          onClick={handleCopy}
          disabled={copying}
          aria-label={`copy ${e.food_name} to today`}
          className={`text-xs px-3 py-2 min-h-[44px] rounded-full ${
            flashed
              ? "bg-emerald-700 text-white"
              : "bg-neutral-800 text-neutral-300 active:bg-neutral-700 disabled:opacity-50"
          }`}
        >
          {flashed ? "copied ✓" : "+ today"}
        </button>
      )}
      <button
        onClick={() => onDelete(e.id)}
        className="text-neutral-500 active:text-red-400 px-3 py-2 min-h-[44px] min-w-[44px]"
        aria-label="delete"
      >
        ✕
      </button>
    </li>
  );
}
```

- [ ] **Step 4: Typecheck + tests**

```bash
cd services/web && npm run typecheck && npm test -- --run
```

Expected: passes.

- [ ] **Step 5: Manual smoke**

In the dev server, navigate to yesterday and:
- Tap `+ today` on a row — confirm "copied ✓" flashes, and switching back to today shows the new entry stamped at "now".
- Tap `+ copy to today` on a meal section — confirm every food in that section appears on today (Water/Vitamins skipped).

- [ ] **Step 6: Commit**

```bash
git add services/web/src/components/TodayMeals.tsx
git commit -m "feat(web): copy past-day entries and meals forward to today"
```

---

### Task 6: Final checks

- [ ] **Step 1: Full test sweep**

```bash
cd services/web && npm run typecheck && npm test -- --run && npm run lint
```

Expected: all green.

- [ ] **Step 2: Push**

```bash
git push origin master
```

(Per project convention: green CI gates auto-deploy via Watchtower.)

---

## Self-Review Notes

- **Spec coverage:** ◀/▶/today strip (Task 2 + Task 4), 30-day floor (Task 2), past-day hides quick log/paste/usuals (Task 4 step 4), per-row + per-meal copy (Task 5), Water/Vitamins excluded (Task 5 `TEMPLATE_EXCLUDED_NAMES` filter), MacroProgressCard prop drill (Task 3), no backend changes (none of these touch services/api). Edit/delete still work on past days — preserved by leaving those buttons in place. ✓
- **Slot semantics:** Copy uses `e.slot` directly — same slot as original, per user. ✓
- **Type consistency:** `DayNav` props match across Task 2 and Task 4. `EntryList` / `SlotSection` / `EntryRow` prop shapes match across Task 4 and Task 5 (placeholders introduced in Task 4 are filled with real values in Task 5). ✓
