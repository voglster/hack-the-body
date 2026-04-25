import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { Food, MealSlot } from "../api/types";

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
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
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
                className="px-3 py-1.5 rounded-full bg-neutral-800 hover:bg-neutral-700 text-sm disabled:opacity-50"
              >
                + {tpl.name}
              </button>
            ))}
          </div>
        </div>
      )}

      <QuickLog onLogged={refresh} />

      <div>
        <div className="text-xs uppercase tracking-wide text-neutral-500 mb-2">
          Today’s log {entries.data ? `(${entries.data.length})` : ""}
        </div>
        {!entries.data?.length ? (
          <div className="text-sm text-neutral-500">nothing logged yet</div>
        ) : (
          <ul className="divide-y divide-neutral-800 text-sm">
            {entries.data.map(e => (
              <li key={e.id} className="py-2 flex justify-between gap-3">
                <div className="min-w-0">
                  <div className="font-medium truncate">{e.food_name}</div>
                  <div className="text-xs text-neutral-500">
                    {e.slot} · {Math.round(e.quantity_g)} g
                    {e.macros.calories ? ` · ${Math.round(e.macros.calories)} cal` : ""}
                    {e.macros.protein_g ? ` · ${Math.round(e.macros.protein_g)} p` : ""}
                  </div>
                </div>
                <button
                  onClick={() => deleteEntry.mutate(e.id)}
                  className="text-xs text-neutral-500 hover:text-red-400"
                  title="delete"
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-3">
      <div className="text-xs uppercase tracking-wide text-neutral-400">{label}</div>
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function QuickLog({ onLogged }: { onLogged: () => void }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Food[]>([]);
  const [picked, setPicked] = useState<Food | null>(null);
  const [qty, setQty] = useState<string>("");
  const [slot, setSlot] = useState<MealSlot>("snack");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const search = async (val: string) => {
    setQ(val);
    setError(null);
    if (val.length < 2) {
      setHits([]);
      return;
    }
    // If looks like a barcode (digits only, 8+ chars), try barcode lookup first
    if (/^\d{8,}$/.test(val)) {
      try {
        const food = await api.foodByBarcode(val);
        setHits([food]);
        return;
      } catch {
        // fall through to text search
      }
    }
    try {
      setHits(await api.searchFoods(val, 8));
    } catch {
      setHits([]);
    }
  };

  const submit = async () => {
    if (!picked || !qty) return;
    setBusy(true);
    setError(null);
    try {
      await api.logEntry({
        food_id: picked.id,
        quantity_g: parseFloat(qty),
        slot,
      });
      setPicked(null);
      setQty("");
      setQ("");
      setHits([]);
      onLogged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-neutral-500 mb-2">Quick log</div>
      <div className="flex flex-col gap-2">
        <input
          value={q}
          onChange={e => { void search(e.target.value); }}
          placeholder="search food name or paste a barcode"
          className="w-full px-3 py-2 rounded bg-neutral-900 border border-neutral-800 text-sm"
        />
        {hits.length > 0 && !picked && (
          <ul className="rounded border border-neutral-800 bg-neutral-900 max-h-48 overflow-auto">
            {hits.map(f => (
              <li
                key={f.id}
                onClick={() => { setPicked(f); setQty(String(f.serving_g)); }}
                className="px-3 py-2 cursor-pointer hover:bg-neutral-800 text-sm"
              >
                <span className="font-medium">{f.name}</span>
                {f.brand && <span className="text-neutral-500"> · {f.brand}</span>}
                {f.per_serving.calories != null && (
                  <span className="text-neutral-500 text-xs">
                    {" "}· {Math.round(f.per_serving.calories)} cal/{f.serving_g}g
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
        {picked && (
          <div className="flex gap-2 items-center">
            <span className="text-sm flex-1 truncate">{picked.name}</span>
            <input
              type="number"
              value={qty}
              onChange={e => setQty(e.target.value)}
              className="w-20 px-2 py-1 rounded bg-neutral-900 border border-neutral-800 text-sm"
            />
            <span className="text-xs text-neutral-500">g</span>
            <select
              value={slot}
              onChange={e => setSlot(e.target.value as MealSlot)}
              className="px-2 py-1 rounded bg-neutral-900 border border-neutral-800 text-sm"
            >
              {SLOTS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <button
              onClick={() => { void submit(); }}
              disabled={busy}
              className="px-3 py-1 rounded bg-emerald-700 hover:bg-emerald-600 text-sm disabled:opacity-50"
            >
              log
            </button>
            <button
              onClick={() => { setPicked(null); setQty(""); }}
              className="text-neutral-500 text-sm"
            >
              ✕
            </button>
          </div>
        )}
        {error && <div className="text-xs text-red-400">{error}</div>}
      </div>
    </div>
  );
}
