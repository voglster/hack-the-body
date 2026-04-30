import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { Food, MealEntry, MealSlot, MealTemplate } from "../api/types";
import { todayLocalISO } from "../lib/tz";
import { BarcodeScanner } from "./BarcodeScanner";
import { DayNav } from "./DayNav";
import { EntryTimeEditor } from "./EntryTimeEditor";
import { MacroProgressCard } from "./MacroProgressCard";
import { PasteFood } from "./PasteFood";

const SLOTS: MealSlot[] = ["breakfast", "lunch", "dinner", "snack", "supplement"];

export function TodayMeals() {
  const qc = useQueryClient();
  const [viewedDay, setViewedDay] = useState<string>(todayLocalISO());
  const isToday = viewedDay === todayLocalISO();
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
  const templates = useQuery({
    queryKey: ["meals.templates"],
    queryFn: api.listTemplates,
  });

  const refresh = () => {
    void qc.invalidateQueries({
      predicate: q => {
        const k = q.queryKey[0];
        return k === "meals.totals" || k === "meals.entries";
      },
    });
  };

  const logTemplate = useMutation({
    mutationFn: (id: string) => api.logTemplate(id),
    onSuccess: refresh,
  });

  const deleteEntry = useMutation({
    mutationFn: (id: string) => api.deleteEntry(id),
    onSuccess: refresh,
  });

  const editEntry = useMutation({
    mutationFn: (args: { id: string; patch: { ts?: string; slot?: MealSlot } }) =>
      api.editEntry(args.id, args.patch),
    onSuccess: () => {
      // Water totals share the meal_entries table.
      void qc.invalidateQueries({ queryKey: ["water.today"] });
      refresh();
    },
  });

  const renameFood = async (food_id: string, name: string) => {
    await api.renameFood(food_id, name);
    refresh();
  };

  const createTemplate = useMutation({
    mutationFn: (t: { name: string; default_slot: MealSlot; items: { food_id: string; quantity_g: number }[] }) =>
      api.createTemplate(t),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["meals.templates"] }),
  });

  const deleteTemplate = useMutation({
    mutationFn: (id: string) => api.deleteTemplate(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["meals.templates"] }),
  });

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

  const saveSlotAsUsual = (slot: MealSlot, list: MealEntry[], name: string) => {
    const items = list
      .filter(e => e.food_name !== "Water" && e.food_name !== "Vitamins")
      .map(e => ({ food_id: e.food_id, quantity_g: e.quantity_g }));
    if (items.length === 0) return;
    createTemplate.mutate({ name: name.trim(), default_slot: slot, items });
  };

  const [editingId, setEditingId] = useState<string | null>(null);
  const editing = entries.data?.find(e => e.id === editingId) ?? null;
  const [manageUsuals, setManageUsuals] = useState(false);

  const t = totals.data?.totals;
  const usuals = isToday ? templates.data ?? [] : [];
  // Water has its own card and adds clutter/false-precision timing rows to
  // the food log. Hide it here; vitamins still show under Supplements.
  const visibleEntries = (entries.data ?? []).filter(e => e.food_name !== "Water");

  return (
    <div className="space-y-4 sm:space-y-6">
      <DayNav day={viewedDay} onChange={setViewedDay} />
      <MacroProgressCard day={isToday ? undefined : viewedDay} />
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-3">
        <Stat label="Calories" value={t ? Math.round(t.calories).toLocaleString() : "0"} />
        <Stat label="Protein" value={t ? `${Math.round(t.protein_g)} g` : "0 g"} />
        <Stat label="Carbs" value={t ? `${Math.round(t.carbs_g)} g` : "0 g"} />
        <Stat label="Fat" value={t ? `${Math.round(t.fat_g)} g` : "0 g"} />
      </div>

      {usuals.length > 0 && (
        <UsualsBar
          templates={usuals}
          manage={manageUsuals}
          onToggleManage={() => setManageUsuals(v => !v)}
          onLog={(id) => logTemplate.mutate(id)}
          onDelete={(id) => deleteTemplate.mutate(id)}
          loggingPending={logTemplate.isPending}
          deletingPending={deleteTemplate.isPending}
        />
      )}

      {isToday && (
        <>
          <PasteFood onLogged={refresh} />
          <QuickLog onLogged={refresh} />
        </>
      )}
      <EditorPane
        editing={editing}
        dayEntries={visibleEntries}
        busy={editEntry.isPending}
        onCancel={() => setEditingId(null)}
        onRenameFood={renameFood}
        onSave={(id, patch) => {
          editEntry.mutate({ id, patch }, {
            onSuccess: () => setEditingId(null),
          });
        }}
      />
      <EntryList
        entries={visibleEntries}
        onDelete={(id) => deleteEntry.mutate(id)}
        onEdit={setEditingId}
        onSaveSlotAsUsual={saveSlotAsUsual}
        savingUsual={createTemplate.isPending}
        isToday={isToday}
        onCopyEntry={(e) => copyOneToToday.mutate(e)}
        onCopyMeal={(list) => copyMealToToday.mutate(list)}
        copying={copyOneToToday.isPending || copyMealToToday.isPending}
      />
    </div>
  );
}

function EditorPane({ editing, dayEntries, busy, onCancel, onRenameFood, onSave }: {
  editing: MealEntry | null;
  dayEntries: MealEntry[];
  busy: boolean;
  onCancel: () => void;
  onRenameFood: (food_id: string, name: string) => Promise<void>;
  onSave: (id: string, patch: { ts?: string; slot?: MealSlot }) => void;
}) {
  if (!editing) return null;
  return (
    <EntryTimeEditor
      entry={editing}
      dayEntries={dayEntries}
      busy={busy}
      onCancel={onCancel}
      onRenameFood={onRenameFood}
      onSave={(patch) => onSave(editing.id, patch)}
    />
  );
}

function UsualsBar({ templates, manage, onToggleManage, onLog, onDelete, loggingPending, deletingPending }: {
  templates: MealTemplate[];
  manage: boolean;
  onToggleManage: () => void;
  onLog: (id: string) => void;
  onDelete: (id: string) => void;
  loggingPending: boolean;
  deletingPending: boolean;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs uppercase tracking-wide text-neutral-500">My usuals</div>
        <button
          onClick={onToggleManage}
          className="text-[11px] text-neutral-500 active:text-neutral-200 px-2 py-1"
          aria-label={manage ? "done managing" : "manage usuals"}
        >
          {manage ? "done" : "manage"}
        </button>
      </div>
      <div className="flex flex-wrap gap-2">
        {templates.map(tpl => (
          <div key={tpl.id} className="flex items-stretch">
            <button
              onClick={() => !manage && tpl.id && onLog(tpl.id)}
              disabled={loggingPending || manage}
              className={`px-3 py-2 text-sm min-h-[44px] ${
                manage
                  ? "rounded-l-full bg-neutral-800 text-neutral-300 disabled:opacity-100"
                  : "rounded-full bg-neutral-800 active:bg-neutral-600 disabled:opacity-50"
              }`}
            >
              + {tpl.name}
            </button>
            {manage && tpl.id && (
              <button
                onClick={() => {
                  if (confirm(`Delete usual "${tpl.name}"?`)) {
                    onDelete(tpl.id!);
                  }
                }}
                disabled={deletingPending}
                className="px-3 py-2 rounded-r-full bg-red-900/60 active:bg-red-800 text-red-200 text-sm min-h-[44px]"
                aria-label={`delete ${tpl.name}`}
              >
                ✕
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-3">
      <div className="text-xs uppercase tracking-wide text-neutral-400">{label}</div>
      <div className="text-xl sm:text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}

// Display order for slot groupings — chronological-by-meal, not insertion.
const SLOT_ORDER: MealSlot[] = ["breakfast", "lunch", "dinner", "snack", "supplement"];
const SLOT_LABEL: Record<MealSlot, string> = {
  breakfast: "Breakfast",
  lunch: "Lunch",
  dinner: "Dinner",
  snack: "Snacks",
  supplement: "Supplements",
};

function groupBySlot(entries: MealEntry[]): Map<MealSlot, MealEntry[]> {
  const out = new Map<MealSlot, MealEntry[]>();
  for (const slot of SLOT_ORDER) out.set(slot, []);
  for (const e of entries) {
    let bucket = out.get(e.slot);
    if (!bucket) {
      bucket = [];
      out.set(e.slot, bucket);
    }
    bucket.push(e);
  }
  // Sort each bucket chronologically so a snack added before a snack still
  // shows in the order it was eaten.
  for (const [, list] of out) list.sort((a, b) => a.ts.localeCompare(b.ts));
  return out;
}

function slotTotals(list: MealEntry[]): { cal: number; protein: number } {
  let cal = 0, protein = 0;
  for (const e of list) {
    cal += e.macros.calories ?? 0;
    protein += e.macros.protein_g ?? 0;
  }
  return { cal, protein };
}

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
  const header = isToday ? "Today’s log" : "Day log";
  if (!entries?.length) {
    return (
      <div>
        <div className="text-xs uppercase tracking-wide text-neutral-500 mb-2">{header}</div>
        <div className="text-sm text-neutral-500">
          {isToday ? "nothing logged yet" : "nothing logged this day"}
        </div>
      </div>
    );
  }
  const grouped = groupBySlot(entries);
  const visibleSlots = SLOT_ORDER.filter(s => (grouped.get(s)?.length ?? 0) > 0);
  return (
    <div className="space-y-4">
      <div className="text-xs uppercase tracking-wide text-neutral-500">
        {header} ({entries.length})
      </div>
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
    </div>
  );
}

/** Names of singleton "auto-managed" foods we don't want to bundle into a
 *  saved template (water and the daily vitamin stack). */
const TEMPLATE_EXCLUDED_NAMES = new Set(["Water", "Vitamins"]);

function templateableEntries(list: MealEntry[]): MealEntry[] {
  return list.filter(e => !TEMPLATE_EXCLUDED_NAMES.has(e.food_name));
}

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
  const { cal, protein } = slotTotals(list);
  const summaryParts = [
    cal > 0 ? `${Math.round(cal)} cal` : "",
    protein > 0 ? `${Math.round(protein)} p` : "",
  ].filter(Boolean);
  const saveable = templateableEntries(list);
  const [naming, setNaming] = useState(false);
  const [nameValue, setNameValue] = useState("");

  const beginNaming = () => {
    // Default name: the foods, joined. e.g. "Yogurt + Protein Powder + Granola"
    // Capped at 3 components so the chip stays compact; the user can edit.
    const parts = saveable.map(e => e.food_name);
    const joined = parts.length <= 3
      ? parts.join(" + ")
      : `${parts.slice(0, 3).join(" + ")} +${parts.length - 3}`;
    setNameValue(joined || SLOT_LABEL[slot]);
    setNaming(true);
  };

  return (
    <section>
      <div className="flex items-baseline justify-between gap-3 mb-1">
        <h3 className="text-sm font-medium text-neutral-300">{SLOT_LABEL[slot]}</h3>
        <div className="flex items-baseline gap-3">
          <span className="text-[11px] text-neutral-500 tabular-nums">
            {summaryParts.join(" · ")}
          </span>
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
        </div>
      </div>
      {naming && (
        <div className="mb-2 flex items-center gap-2 rounded-lg bg-neutral-900 border border-neutral-800 p-2">
          <input
            value={nameValue}
            onChange={e => setNameValue(e.target.value)}
            disabled={savingUsual}
            autoFocus
            placeholder="usual name"
            className="flex-1 min-w-0 px-2 py-2 rounded bg-neutral-800 border border-neutral-700 text-sm"
            aria-label="usual name"
          />
          <button
            onClick={() => {
              if (!nameValue.trim()) return;
              onSaveAsUsual(slot, saveable, nameValue);
              setNaming(false);
            }}
            disabled={savingUsual || !nameValue.trim()}
            className="px-3 py-2 rounded bg-emerald-700 active:bg-emerald-800 text-white text-sm disabled:opacity-50"
          >
            {savingUsual ? "..." : "save"}
          </button>
          <button
            onClick={() => setNaming(false)}
            disabled={savingUsual}
            className="px-2 py-2 text-neutral-400 text-sm"
            aria-label="cancel"
          >
            ✕
          </button>
        </div>
      )}
      <ul className="divide-y divide-neutral-800 text-sm">
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
      </ul>
    </section>
  );
}

function fmtClock(iso: string): string {
  const d = new Date(iso);
  const h = d.getHours();
  const m = d.getMinutes().toString().padStart(2, "0");
  const ampm = h >= 12 ? "p" : "a";
  return `${h % 12 === 0 ? 12 : h % 12}:${m}${ampm}`;
}

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
  // slot is implicit from the section header now, so leave it out here.
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

// ---------- Quick log ----------

interface QuickLogState {
  q: string;
  hits: Food[];
  picked: Food | null;
  qty: string;
  slot: MealSlot;
  scanning: boolean;
  busy: boolean;
  error: string | null;
  // When set, the user scanned/typed a barcode that's not in OFF or our DB.
  // We surface a small "create custom food" form so they can move forward.
  unknownBarcode: string | null;
}

function QuickLog({ onLogged }: { onLogged: () => void }) {
  const [s, setS] = useState<QuickLogState>({
    q: "", hits: [], picked: null, qty: "",
    slot: "snack", scanning: false, busy: false, error: null,
    unknownBarcode: null,
  });
  const update = (patch: Partial<QuickLogState>) => setS(p => ({ ...p, ...patch }));

  const search = async (val: string) => {
    update({ q: val, error: null, unknownBarcode: null });
    if (val.length < 2) { update({ hits: [] }); return; }
    if (/^\d{8,}$/.test(val)) {
      try {
        const food = await api.foodByBarcode(val);
        // qty here is *servings*, not grams — default to 1 serving so we
        // don't accidentally log "325 servings" for a 325 g shake.
        update({ hits: [food], picked: food, qty: "1" });
        return;
      } catch { /* fall through to text search */ }
    }
    try { update({ hits: await api.searchFoods(val, 8) }); }
    catch { update({ hits: [] }); }
  };

  const onScanned = (barcode: string) => {
    // Show the entry form instantly. Lookup happens inside the form so the
    // user can start typing the name immediately — if OFF/cache returns a
    // hit it pre-fills any empty fields, otherwise the user just fills in
    // what they know now and details can be added later.
    update({ scanning: false, q: barcode, unknownBarcode: barcode, picked: null });
  };

  const onCustomCreated = (food: Food) => {
    // After creating a manual food, default to logging 1 serving of it.
    update({
      unknownBarcode: null, picked: food, qty: "1",
      hits: [food], q: food.name, error: null,
    });
  };

  const submit = async () => {
    if (!s.picked || !s.qty) return;
    update({ busy: true, error: null });
    try {
      const servings = parseFloat(s.qty);
      const grams = servings * (s.picked.serving_g || 100);
      await api.logEntry({
        food_id: s.picked.id, quantity_g: grams, slot: s.slot,
      });
      setS({ q: "", hits: [], picked: null, qty: "",
             slot: s.slot, scanning: false, busy: false, error: null,
             unknownBarcode: null });
      onLogged();
    } catch (err) {
      update({ busy: false, error: (err as Error).message });
    }
  };

  return (
    <div className="space-y-2">
      <div className="text-xs uppercase tracking-wide text-neutral-500">Quick log</div>
      {s.scanning && (
        <BarcodeScanner
          onScanned={onScanned}
          onClose={() => update({ scanning: false })}
        />
      )}
      <SearchRow
        q={s.q}
        onChange={(v) => { void search(v); }}
        onScan={() => update({ scanning: true })}
      />
      {s.hits.length > 0 && !s.picked && (
        <FoodPickerList hits={s.hits} onPick={(f) => update({ picked: f, qty: "1" })} />
      )}
      {s.picked && (
        <PickedRow
          food={s.picked} servings={s.qty} slot={s.slot} busy={s.busy}
          onServings={(qty) => update({ qty })}
          onSlot={(slot) => update({ slot })}
          onSubmit={() => { void submit(); }}
          onCancel={() => update({ picked: null, qty: "" })}
        />
      )}
      {s.unknownBarcode && !s.picked && (
        <CreateFromBarcode
          barcode={s.unknownBarcode}
          onCreated={onCustomCreated}
          onCancel={() => update({ unknownBarcode: null })}
        />
      )}
      {s.error && <div className="text-xs text-red-400">{s.error}</div>}
    </div>
  );
}

function SearchRow({ q, onChange, onScan }: {
  q: string; onChange: (v: string) => void; onScan: () => void;
}) {
  const supportsScan = typeof window !== "undefined" && "BarcodeDetector" in window;
  return (
    <div className="flex gap-2">
      <input
        value={q}
        onChange={e => onChange(e.target.value)}
        placeholder="search food name or paste a barcode"
        className="flex-1 px-3 py-3 rounded bg-neutral-900 border border-neutral-800 text-base"
        autoCapitalize="none"
        autoCorrect="off"
      />
      {supportsScan && (
        <button
          onClick={onScan}
          className="px-4 py-3 rounded bg-emerald-700 active:bg-emerald-800 text-white min-w-[60px]"
          aria-label="scan barcode"
          title="scan barcode"
        >
          📷
        </button>
      )}
    </div>
  );
}

function FoodPickerList({ hits, onPick }: {
  hits: Food[]; onPick: (f: Food) => void;
}) {
  return (
    <ul className="rounded border border-neutral-800 bg-neutral-900 max-h-56 overflow-auto">
      {hits.map(f => (
        <li key={f.id}>
          <button
            onClick={() => onPick(f)}
            className="w-full text-left px-3 py-3 active:bg-neutral-700 text-sm min-h-[44px]"
          >
            <div className="font-medium">{f.name}</div>
            <div className="text-xs text-neutral-500">
              {[f.brand, f.per_serving.calories != null
                ? `${Math.round(f.per_serving.calories)} cal/${f.serving_g}g`
                : null].filter(Boolean).join(" · ")}
            </div>
          </button>
        </li>
      ))}
    </ul>
  );
}

function CreateFromBarcode({ barcode, onCreated, onCancel }: {
  barcode: string;
  onCreated: (f: Food) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [brand, setBrand] = useState("");
  const [serving, setServing] = useState("");
  const [cal, setCal] = useState("");
  const [p, setP] = useState("");
  const [c, setC] = useState("");
  const [f, setF] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [lookup, setLookup] = useState<"pending" | "hit" | "miss">("pending");
  // If lookup hit, this is the already-saved Food — submit logs against it
  // directly without creating a duplicate.
  const [existing, setExisting] = useState<Food | null>(null);

  // Run the OFF / cache lookup once on mount. Pre-fill any field the user
  // hasn't touched yet using a functional setter (so we never clobber input).
  useEffect(() => {
    let cancelled = false;
    const fillIfEmpty = (cur: string, val: string | number | null | undefined): string =>
      cur || (val == null ? cur : String(val));
    api.foodByBarcode(barcode).then(food => {
      if (cancelled) return;
      setExisting(food);
      setLookup("hit");
      setName(prev => fillIfEmpty(prev, food.name));
      setBrand(prev => fillIfEmpty(prev, food.brand ?? ""));
      setServing(prev => fillIfEmpty(prev, food.serving_g));
      setCal(prev => fillIfEmpty(prev, food.per_serving.calories));
      setP(prev => fillIfEmpty(prev, food.per_serving.protein_g));
      setC(prev => fillIfEmpty(prev, food.per_serving.carbs_g));
      setF(prev => fillIfEmpty(prev, food.per_serving.fat_g));
    }).catch(() => { if (!cancelled) setLookup("miss"); });
    return () => { cancelled = true; };
  }, [barcode]);

  const num = (v: string): number | null => {
    const n = parseFloat(v);
    return Number.isFinite(n) ? n : null;
  };

  const submit = async () => {
    if (!name.trim()) { setErr("name is required"); return; }
    setBusy(true); setErr(null);
    try {
      // If lookup found an existing Food row, just hand that back so the
      // caller can log against it. Otherwise create a new manual food.
      const food = existing ?? await api.createFood({
        name: name.trim(),
        brand: brand.trim() || null,
        barcode,
        category: "food",
        serving_g: num(serving) ?? 100,
        serving_label: `${num(serving) ?? 100} g`,
        per_serving: {
          calories: num(cal),
          protein_g: num(p),
          carbs_g: num(c),
          fat_g: num(f),
        },
        source: "manual",
      });
      onCreated(food);
    } catch (e) {
      setErr((e as Error).message);
      setBusy(false);
    }
  };

  const status = lookup === "pending"
    ? <span className="text-sky-300">looking up {barcode}…</span>
    : lookup === "hit"
      ? <span className="text-emerald-300">found in OFF — review and log</span>
      : <span className="text-amber-300">no match for {barcode} — fill what you know</span>;

  return (
    <div className="space-y-2 rounded-lg border border-amber-800/40 bg-amber-950/20 p-3">
      <div className="text-sm">{status}</div>
      <input
        value={name} onChange={e => setName(e.target.value)}
        placeholder="name (required)" autoFocus
        className="w-full px-3 py-3 rounded bg-neutral-900 border border-neutral-800 text-base"
      />
      <input
        value={brand} onChange={e => setBrand(e.target.value)}
        placeholder="brand (optional)"
        className="w-full px-3 py-3 rounded bg-neutral-900 border border-neutral-800 text-base"
      />
      <div className="grid grid-cols-2 gap-2">
        <Field label="serving (g)" v={serving} onV={setServing} placeholder="100" />
        <Field label="calories" v={cal} onV={setCal} placeholder="per serving" />
        <Field label="protein (g)" v={p} onV={setP} />
        <Field label="carbs (g)" v={c} onV={setC} />
        <Field label="fat (g)" v={f} onV={setF} />
      </div>
      {err && <div className="text-xs text-red-400">{err}</div>}
      <div className="flex gap-2">
        <button
          onClick={() => { void submit(); }}
          disabled={busy}
          className="flex-1 px-3 py-3 rounded bg-amber-700 active:bg-amber-800 text-white text-base font-medium disabled:opacity-50 min-h-[44px]"
        >
          {busy ? "saving..." : "save & log"}
        </button>
        <button
          onClick={onCancel}
          className="px-4 py-3 rounded bg-neutral-800 active:bg-neutral-600 text-sm min-h-[44px]"
        >
          cancel
        </button>
      </div>
    </div>
  );
}

function Field({ label, v, onV, placeholder }: {
  label: string; v: string; onV: (s: string) => void; placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="text-xs text-neutral-500">{label}</span>
      <input
        type="number" inputMode="decimal" value={v}
        onChange={e => onV(e.target.value)}
        placeholder={placeholder}
        className="w-full px-3 py-3 rounded bg-neutral-900 border border-neutral-800 text-base"
      />
    </label>
  );
}

const SERVING_PRESETS = [0.5, 1, 1.5, 2];

function buildPreview(food: Food, n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "";
  const grams = n * food.serving_g;
  const parts: string[] = [`≈ ${grams.toFixed(0)} g`];
  if (food.category === "drink") {
    parts.push(`${(grams / 29.5735).toFixed(1)} fl oz`);
  }
  const cal = food.per_serving.calories;
  const protein = food.per_serving.protein_g;
  if (cal != null) parts.push(`${Math.round(cal * n)} cal`);
  if (protein != null) parts.push(`${Math.round(protein * n)}g protein`);
  return parts.join(" · ");
}

function PickedRow({ food, servings, slot, busy, onServings, onSlot, onSubmit, onCancel }: {
  food: Food; servings: string; slot: MealSlot; busy: boolean;
  onServings: (v: string) => void; onSlot: (s: MealSlot) => void;
  onSubmit: () => void; onCancel: () => void;
}) {
  const n = parseFloat(servings);
  const sublabel = food.serving_label ?? `${food.serving_g.toFixed(0)} g`;
  const preview = buildPreview(food, n);
  return (
    <div className="space-y-3 rounded-lg border border-emerald-800/40 bg-emerald-950/20 p-3">
      <div>
        <div className="text-sm font-medium">{food.name}</div>
        <div className="text-xs text-neutral-500">1 serving = {sublabel}</div>
      </div>
      <div className="space-y-2">
        <div className="text-xs text-neutral-500">servings</div>
        <div className="flex flex-wrap gap-2">
          {SERVING_PRESETS.map(p => (
            <button
              key={p}
              onClick={() => onServings(String(p))}
              className={`px-3 py-2 rounded-full text-sm min-h-[44px] tabular-nums ${
                Math.abs(n - p) < 0.001
                  ? "bg-emerald-700 text-white"
                  : "bg-neutral-800 active:bg-neutral-700 text-neutral-300"
              }`}
            >
              {p === 0.5 ? "½" : p}
            </button>
          ))}
          <input
            type="number" inputMode="decimal" step="0.25" value={servings}
            onChange={e => onServings(e.target.value)}
            className="w-20 px-3 py-2 rounded bg-neutral-900 border border-neutral-800 text-base tabular-nums"
            aria-label="servings"
          />
        </div>
        <div className="text-xs text-neutral-500 tabular-nums">{preview}</div>
      </div>
      <label className="block">
        <span className="text-xs text-neutral-500">meal</span>
        <select
          value={slot} onChange={e => onSlot(e.target.value as MealSlot)}
          className="w-full px-3 py-3 rounded bg-neutral-900 border border-neutral-800 text-base"
        >
          {SLOTS.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
      </label>
      <div className="flex gap-2">
        <button
          onClick={onSubmit} disabled={busy || !Number.isFinite(n) || n <= 0}
          className="flex-1 px-3 py-3 rounded bg-emerald-700 active:bg-emerald-800 text-white text-base font-medium disabled:opacity-50 min-h-[44px]"
        >
          {busy ? "logging..." : "log it"}
        </button>
        <button
          onClick={onCancel}
          className="px-4 py-3 rounded bg-neutral-800 active:bg-neutral-600 text-sm min-h-[44px]"
        >
          ✕
        </button>
      </div>
    </div>
  );
}
