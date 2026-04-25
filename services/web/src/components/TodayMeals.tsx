import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { Food, MealEntry, MealSlot } from "../api/types";
import { BarcodeScanner } from "./BarcodeScanner";

const SLOTS: MealSlot[] = ["breakfast", "lunch", "dinner", "snack", "supplement"];

export function TodayMeals() {
  const qc = useQueryClient();
  const totals = useQuery({
    queryKey: ["meals.today.totals"],
    queryFn: api.todayTotals,
    refetchInterval: 60_000,
  });
  const entries = useQuery({
    queryKey: ["meals.today.entries"],
    queryFn: api.todayEntries,
    refetchInterval: 60_000,
  });
  const templates = useQuery({
    queryKey: ["meals.templates"],
    queryFn: api.listTemplates,
  });

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["meals.today.totals"] });
    void qc.invalidateQueries({ queryKey: ["meals.today.entries"] });
  };

  const logTemplate = useMutation({
    mutationFn: (id: string) => api.logTemplate(id),
    onSuccess: refresh,
  });

  const deleteEntry = useMutation({
    mutationFn: (id: string) => api.deleteEntry(id),
    onSuccess: refresh,
  });

  const t = totals.data?.totals;

  return (
    <div className="space-y-4 sm:space-y-6">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 sm:gap-3">
        <Stat label="Calories" value={t ? Math.round(t.calories).toLocaleString() : "0"} />
        <Stat label="Protein" value={t ? `${Math.round(t.protein_g)} g` : "0 g"} />
        <Stat label="Carbs" value={t ? `${Math.round(t.carbs_g)} g` : "0 g"} />
        <Stat label="Fat" value={t ? `${Math.round(t.fat_g)} g` : "0 g"} />
      </div>

      {templates.data && templates.data.length > 0 && (
        <div>
          <div className="text-xs uppercase tracking-wide text-neutral-500 mb-2">My usuals</div>
          <div className="flex flex-wrap gap-2">
            {templates.data.map(tpl => (
              <button
                key={tpl.id}
                onClick={() => logTemplate.mutate(tpl.id)}
                disabled={logTemplate.isPending}
                className="px-3 py-2 rounded-full bg-neutral-800 active:bg-neutral-600 text-sm disabled:opacity-50 min-h-[44px]"
              >
                + {tpl.name}
              </button>
            ))}
          </div>
        </div>
      )}

      <QuickLog onLogged={refresh} />
      <EntryList entries={entries.data} onDelete={(id) => deleteEntry.mutate(id)} />
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

function EntryList({ entries, onDelete }: {
  entries: MealEntry[] | undefined;
  onDelete: (id: string) => void;
}) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-neutral-500 mb-2">
        Today’s log {entries ? `(${entries.length})` : ""}
      </div>
      {!entries?.length ? (
        <div className="text-sm text-neutral-500">nothing logged yet</div>
      ) : (
        <ul className="divide-y divide-neutral-800 text-sm">
          {entries.map(e => <EntryRow key={e.id} entry={e} onDelete={onDelete} />)}
        </ul>
      )}
    </div>
  );
}

function EntryRow({ entry: e, onDelete }: {
  entry: MealEntry;
  onDelete: (id: string) => void;
}) {
  const cal = e.macros.calories ? `${Math.round(e.macros.calories)} cal` : "";
  const protein = e.macros.protein_g ? `${Math.round(e.macros.protein_g)} p` : "";
  const detailParts = [`${e.slot}`, `${Math.round(e.quantity_g)}g`, cal, protein].filter(Boolean);
  return (
    <li className="py-3 flex justify-between gap-3 items-center">
      <div className="min-w-0 flex-1">
        <div className="font-medium truncate">{e.food_name}</div>
        <div className="text-xs text-neutral-500">{detailParts.join(" · ")}</div>
      </div>
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
}

function QuickLog({ onLogged }: { onLogged: () => void }) {
  const [s, setS] = useState<QuickLogState>({
    q: "", hits: [], picked: null, qty: "",
    slot: "snack", scanning: false, busy: false, error: null,
  });
  const update = (patch: Partial<QuickLogState>) => setS(p => ({ ...p, ...patch }));

  const search = async (val: string) => {
    update({ q: val, error: null });
    if (val.length < 2) { update({ hits: [] }); return; }
    if (/^\d{8,}$/.test(val)) {
      try {
        const food = await api.foodByBarcode(val);
        update({ hits: [food], picked: food, qty: String(food.serving_g) });
        return;
      } catch { /* fall through */ }
    }
    try { update({ hits: await api.searchFoods(val, 8) }); }
    catch { update({ hits: [] }); }
  };

  const onScanned = async (barcode: string) => {
    update({ scanning: false, q: barcode });
    try {
      const food = await api.foodByBarcode(barcode);
      update({ picked: food, qty: String(food.serving_g), hits: [food] });
    } catch {
      update({ error: "barcode not found in Open Food Facts — try typing the name" });
    }
  };

  const submit = async () => {
    if (!s.picked || !s.qty) return;
    update({ busy: true, error: null });
    try {
      await api.logEntry({
        food_id: s.picked.id, quantity_g: parseFloat(s.qty), slot: s.slot,
      });
      setS({ q: "", hits: [], picked: null, qty: "",
             slot: s.slot, scanning: false, busy: false, error: null });
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
          onScanned={(b) => { void onScanned(b); }}
          onClose={() => update({ scanning: false })}
        />
      )}
      <SearchRow
        q={s.q}
        onChange={(v) => { void search(v); }}
        onScan={() => update({ scanning: true })}
      />
      {s.hits.length > 0 && !s.picked && (
        <FoodPickerList hits={s.hits} onPick={(f) => update({ picked: f, qty: String(f.serving_g) })} />
      )}
      {s.picked && (
        <PickedRow
          food={s.picked} qty={s.qty} slot={s.slot} busy={s.busy}
          onQty={(qty) => update({ qty })}
          onSlot={(slot) => update({ slot })}
          onSubmit={() => { void submit(); }}
          onCancel={() => update({ picked: null, qty: "" })}
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

function PickedRow({ food, qty, slot, busy, onQty, onSlot, onSubmit, onCancel }: {
  food: Food; qty: string; slot: MealSlot; busy: boolean;
  onQty: (v: string) => void; onSlot: (s: MealSlot) => void;
  onSubmit: () => void; onCancel: () => void;
}) {
  return (
    <div className="space-y-2 rounded-lg border border-emerald-800/40 bg-emerald-950/20 p-3">
      <div className="text-sm font-medium">{food.name}</div>
      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="text-xs text-neutral-500">grams</span>
          <input
            type="number" inputMode="decimal" value={qty}
            onChange={e => onQty(e.target.value)}
            className="w-full px-3 py-3 rounded bg-neutral-900 border border-neutral-800 text-base"
          />
        </label>
        <label className="block">
          <span className="text-xs text-neutral-500">meal</span>
          <select
            value={slot} onChange={e => onSlot(e.target.value as MealSlot)}
            className="w-full px-3 py-3 rounded bg-neutral-900 border border-neutral-800 text-base"
          >
            {SLOTS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
      </div>
      <div className="flex gap-2">
        <button
          onClick={onSubmit} disabled={busy}
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
