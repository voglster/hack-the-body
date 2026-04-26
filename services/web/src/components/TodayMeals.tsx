import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../api/client";
import type { Food, MealEntry, MealSlot } from "../api/types";
import { BarcodeScanner } from "./BarcodeScanner";
import { EntryTimeEditor } from "./EntryTimeEditor";
import { PasteFood } from "./PasteFood";

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

  const editEntry = useMutation({
    mutationFn: (args: { id: string; patch: { ts?: string; slot?: MealSlot } }) =>
      api.editEntry(args.id, args.patch),
    onSuccess: () => {
      // Water totals share the meal_entries table.
      void qc.invalidateQueries({ queryKey: ["water.today"] });
      refresh();
    },
  });

  const [editingId, setEditingId] = useState<string | null>(null);
  const editing = entries.data?.find(e => e.id === editingId) ?? null;

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

      <PasteFood onLogged={refresh} />
      <QuickLog onLogged={refresh} />
      {editing && (
        <EntryTimeEditor
          entry={editing}
          dayEntries={entries.data ?? []}
          busy={editEntry.isPending}
          onCancel={() => setEditingId(null)}
          onSave={(patch) => {
            editEntry.mutate({ id: editing.id, patch }, {
              onSuccess: () => setEditingId(null),
            });
          }}
        />
      )}
      <EntryList
        entries={entries.data}
        onDelete={(id) => deleteEntry.mutate(id)}
        onEdit={setEditingId}
      />
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

function EntryList({ entries, onDelete, onEdit }: {
  entries: MealEntry[] | undefined;
  onDelete: (id: string) => void;
  onEdit: (id: string) => void;
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
          {entries.map(e => (
            <EntryRow key={e.id} entry={e} onDelete={onDelete} onEdit={onEdit} />
          ))}
        </ul>
      )}
    </div>
  );
}

function fmtClock(iso: string): string {
  const d = new Date(iso);
  const h = d.getHours();
  const m = d.getMinutes().toString().padStart(2, "0");
  const ampm = h >= 12 ? "p" : "a";
  return `${h % 12 === 0 ? 12 : h % 12}:${m}${ampm}`;
}

function EntryRow({ entry: e, onDelete, onEdit }: {
  entry: MealEntry;
  onDelete: (id: string) => void;
  onEdit: (id: string) => void;
}) {
  const cal = e.macros.calories ? `${Math.round(e.macros.calories)} cal` : "";
  const protein = e.macros.protein_g ? `${Math.round(e.macros.protein_g)} p` : "";
  const detailParts = [
    fmtClock(e.ts), e.slot, `${Math.round(e.quantity_g)}g`, cal, protein,
  ].filter(Boolean);
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
