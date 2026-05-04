/**
 * Paste-in food logger. The user pastes a freeform breakdown (often
 * from a chat with another AI) and we run it through the local LLM
 * to extract structured items, which the user reviews and bulk-logs.
 */
import { useState } from "react";

import { api } from "../api/client";
import type { MealSlot, ParsedFoodItem } from "../api/types";
import { slotTimestampUTC } from "../lib/tz";

const SLOTS: MealSlot[] = ["breakfast", "lunch", "dinner", "snack", "supplement"];

function defaultSlot(): MealSlot {
  const h = new Date().getHours();
  if (h < 10) return "breakfast";
  if (h < 14) return "lunch";
  if (h < 16) return "snack";
  if (h < 21) return "dinner";
  return "snack";
}

export function PasteFood({ onLogged, day }: { onLogged: () => void; day: string | null }) {
  const [text, setText] = useState("");
  const [items, setItems] = useState<ParsedFoodItem[] | null>(null);
  // Snapshot of what the parser returned before the user edited anything,
  // so the "this went wrong" report can include both the raw output and
  // the user's corrections.
  const [originalItems, setOriginalItems] = useState<ParsedFoodItem[]>([]);
  const [slot, setSlot] = useState<MealSlot>(defaultSlot());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reported, setReported] = useState(false);

  const onParse = async () => {
    if (!text.trim()) return;
    setBusy(true); setError(null); setReported(false);
    try {
      const res = await api.parseFoodText(text);
      setOriginalItems(res.items);
      if (res.items.length === 0) {
        setError("nothing food-like was found");
        setItems(null);
      } else {
        setItems(res.items);
      }
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const onReport = async () => {
    const note = window.prompt(
      "What went wrong? (optional — describe what should have happened)",
      "",
    );
    if (note === null) return;  // user hit cancel
    try {
      await api.reportParseFailure(
        text,
        originalItems,
        items ?? null,
        note.trim() || null,
      );
      setReported(true);
    } catch (e) {
      setError(`couldn't save report: ${(e as Error).message}`);
    }
  };

  const onLogAll = async () => {
    if (!items?.length) return;
    setBusy(true); setError(null);
    try {
      await api.logParsedFoods(items, slot, day ? slotTimestampUTC(day, slot) : undefined);
      setText(""); setItems(null); setOriginalItems([]); setReported(false);
      onLogged();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    } finally {
      setBusy(false);
    }
  };

  const updateItem = (i: number, patch: Partial<ParsedFoodItem>) => {
    if (!items) return;
    const next = items.slice();
    next[i] = { ...next[i], ...patch };
    setItems(next);
  };
  const removeItem = (i: number) => {
    if (!items) return;
    setItems(items.filter((_, j) => j !== i));
  };

  const totalCal = items?.reduce((a, b) => a + (b.calories ?? 0), 0) ?? 0;
  const totalProtein = items?.reduce((a, b) => a + (b.protein_g ?? 0), 0) ?? 0;
  const totalCarbs = items?.reduce((a, b) => a + (b.carbs_g ?? 0), 0) ?? 0;
  const totalFat = items?.reduce((a, b) => a + (b.fat_g ?? 0), 0) ?? 0;

  return (
    <div className="space-y-2 rounded-lg border border-sky-800/40 bg-sky-950/20 p-3">
      <div className="text-xs uppercase tracking-wide text-sky-300">Paste a meal</div>
      <textarea
        value={text}
        onChange={e => setText(e.target.value)}
        placeholder={"paste a breakdown — e.g.\n\nCrepe Shell: 250\n2 Scrambled Eggs: 150\nSmoked Salmon (2oz): 80\nAlmond Milk Latte: 110"}
        rows={5}
        className="w-full px-3 py-2 rounded bg-neutral-900 border border-neutral-800 text-sm font-mono"
      />
      {!items && (
        <div className="flex gap-2">
          <button
            onClick={() => { void onParse(); }}
            disabled={busy || !text.trim()}
            className="flex-1 px-3 py-3 rounded bg-sky-700 active:bg-sky-800 text-white text-base font-medium disabled:opacity-50 min-h-[44px]"
          >
            {busy ? "parsing..." : "parse"}
          </button>
        </div>
      )}
      {items && (
        <ItemReview
          items={items}
          slot={slot}
          busy={busy}
          totalCal={totalCal}
          totalProtein={totalProtein}
          totalCarbs={totalCarbs}
          totalFat={totalFat}
          onUpdate={updateItem}
          onRemove={removeItem}
          onSlot={setSlot}
          onSubmit={() => { void onLogAll(); }}
          onCancel={() => { setItems(null); }}
        />
      )}
      {error && <div className="text-xs text-red-400">{error}</div>}
      {/* Flag a bad parse — visible whenever we have something to report
          (parser returned items, OR returned nothing on a non-empty paste). */}
      {(originalItems.length > 0 || (text.trim() && error)) && (
        <div className="text-right">
          {reported ? (
            <span className="text-[11px] text-emerald-400">thanks — saved for review</span>
          ) : (
            <button
              onClick={() => { void onReport(); }}
              className="text-[11px] text-neutral-500 hover:text-amber-300 underline underline-offset-2"
            >
              this went wrong
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function ItemReview({
  items, slot, busy, totalCal, totalProtein, totalCarbs, totalFat,
  onUpdate, onRemove, onSlot, onSubmit, onCancel,
}: {
  items: ParsedFoodItem[]; slot: MealSlot; busy: boolean;
  totalCal: number; totalProtein: number; totalCarbs: number; totalFat: number;
  onUpdate: (i: number, p: Partial<ParsedFoodItem>) => void;
  onRemove: (i: number) => void;
  onSlot: (s: MealSlot) => void;
  onSubmit: () => void;
  onCancel: () => void;
}) {
  // Per-item layout is two rows: name + delete on top, four macro inputs
  // below. Single-row would crush on a 360 px phone.
  const macroField = (
    i: number,
    key: "calories" | "protein_g" | "carbs_g" | "fat_g",
    placeholder: string,
    value: number | null,
  ) => (
    <input
      type="number" inputMode="decimal" step="1"
      value={value ?? ""}
      onChange={e => onUpdate(i, {
        [key]: e.target.value === "" ? null : parseFloat(e.target.value),
      } as Partial<ParsedFoodItem>)}
      placeholder={placeholder}
      className="w-full px-2 py-2 rounded bg-neutral-900 border border-neutral-800 text-sm text-right tabular-nums"
    />
  );

  return (
    <div className="space-y-2">
      <ul className="divide-y divide-neutral-800">
        {items.map((it, i) => (
          <li key={i} className="py-2 space-y-1.5">
            <div className="flex gap-2 items-center">
              <input
                value={it.name}
                onChange={e => onUpdate(i, { name: e.target.value })}
                className="flex-1 min-w-0 px-2 py-2 rounded bg-neutral-900 border border-neutral-800 text-sm"
              />
              <button
                onClick={() => onRemove(i)}
                className="text-neutral-500 active:text-red-400 px-2 py-2 min-h-[44px]"
                aria-label="remove"
              >
                ✕
              </button>
            </div>
            <div className="grid grid-cols-4 gap-1.5">
              {macroField(i, "calories", "cal", it.calories)}
              {macroField(i, "protein_g", "p", it.protein_g)}
              {macroField(i, "fat_g", "f", it.fat_g)}
              {macroField(i, "carbs_g", "c", it.carbs_g)}
            </div>
          </li>
        ))}
      </ul>
      <div className="text-xs text-neutral-400 tabular-nums">
        total: {Math.round(totalCal)} cal · P {Math.round(totalProtein)}g
        · F {Math.round(totalFat)}g · C {Math.round(totalCarbs)}g
      </div>
      <div className="flex gap-2 items-center">
        <select
          value={slot} onChange={e => onSlot(e.target.value as MealSlot)}
          className="px-3 py-3 rounded bg-neutral-900 border border-neutral-800 text-base"
        >
          {SLOTS.map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <button
          onClick={onSubmit}
          disabled={busy || items.length === 0}
          className="flex-1 px-3 py-3 rounded bg-sky-700 active:bg-sky-800 text-white text-base font-medium disabled:opacity-50 min-h-[44px]"
        >
          {busy ? "logging..." : `log ${items.length} item${items.length === 1 ? "" : "s"}`}
        </button>
        <button
          onClick={onCancel}
          className="px-4 py-3 rounded bg-neutral-800 active:bg-neutral-600 text-sm min-h-[44px]"
        >
          back
        </button>
      </div>
    </div>
  );
}
