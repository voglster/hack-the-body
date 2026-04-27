/**
 * Touch-friendly editor for an entry's time-of-day + slot.
 *
 * The day is a single horizontal bar (6am → midnight by default). The
 * entry being edited is a draggable thumb; the rest of today's entries
 * are faint dots so you can see "where everything else is" while you
 * move this one. Snap is 15 minutes — plenty of accuracy for "did I
 * eat that closer to noon or 1pm?".
 */
import { useEffect, useRef, useState } from "react";

import type { MealEntry, MealSlot } from "../api/types";

const SLOTS: MealSlot[] = ["breakfast", "lunch", "dinner", "snack", "supplement"];

const START_HOUR = 4;   // earliest scrubbable time (slightly before breakfast)
const END_HOUR = 24;    // exclusive — midnight
const SNAP_MIN = 15;
const TOTAL_MIN = (END_HOUR - START_HOUR) * 60;

function isValidServings(s: string): boolean {
  const n = parseFloat(s);
  return Number.isFinite(n) && n > 0;
}

function buildPatch(
  entry: MealEntry, t: Date, slot: MealSlot, servingsStr: string,
): { ts: string; slot: MealSlot; quantity_g?: number } {
  const patch: { ts: string; slot: MealSlot; quantity_g?: number } = {
    ts: t.toISOString(),
    slot,
  };
  const n = parseFloat(servingsStr);
  if (Number.isFinite(n) && n > 0) {
    const sg = impliedServingG(entry);
    if (sg != null) {
      const newGrams = round2(n * sg);
      // Only include quantity_g when the user actually changed it.
      if (Math.abs(newGrams - entry.quantity_g) > 0.5) {
        patch.quantity_g = newGrams;
      }
    } else {
      // Fallback: treat the field as raw grams (when servings is unknown).
      if (Math.abs(n - entry.quantity_g) > 0.5) {
        patch.quantity_g = round2(n);
      }
    }
  }
  return patch;
}

function QuantityField({
  entry, servingsStr, onServingsStr, busy,
}: {
  entry: MealEntry;
  servingsStr: string;
  onServingsStr: (s: string) => void;
  busy: boolean;
}) {
  const sg = impliedServingG(entry);
  const n = parseFloat(servingsStr);
  const grams = sg != null && Number.isFinite(n) && n > 0 ? round2(n * sg) : null;
  const label = sg != null ? "servings" : "grams";
  const hint = sg != null
    ? `1 serving ≈ ${round2(sg)} g${grams != null ? ` · ${grams} g total` : ""}`
    : "raw grams (entry's serving size unknown)";
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs uppercase tracking-wide text-neutral-400">{label}</span>
        <span className="text-[11px] text-neutral-500">{hint}</span>
      </div>
      <input
        type="number"
        inputMode="decimal"
        step="0.25"
        value={servingsStr}
        disabled={busy}
        onChange={e => onServingsStr(e.target.value)}
        className="w-full px-3 py-3 rounded bg-neutral-800 border border-neutral-700 text-base tabular-nums"
        aria-label={label}
      />
      {sg != null && (
        <div className="flex flex-wrap gap-2">
          {SERVINGS_PRESETS.map(p => (
            <button
              key={p}
              type="button"
              onClick={() => onServingsStr(String(p))}
              disabled={busy}
              className="px-3 py-1.5 rounded-full text-sm bg-neutral-800 active:bg-neutral-700 text-neutral-300"
            >
              {p}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Per-serving grams, derived from the entry. Returns null if we can't trust
 *  the math (e.g. servings was logged as 0 or null) — caller should fall back
 *  to direct-grams editing. */
function impliedServingG(entry: MealEntry): number | null {
  if (!entry.servings || entry.servings <= 0) return null;
  const v = entry.quantity_g / entry.servings;
  if (!Number.isFinite(v) || v <= 0) return null;
  return v;
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}

const SERVINGS_PRESETS = [0.5, 1, 1.5, 2];

function fmtTime(d: Date): string {
  const h = d.getHours();
  const m = d.getMinutes().toString().padStart(2, "0");
  const ampm = h >= 12 ? "pm" : "am";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${m} ${ampm}`;
}

function toMinutesFromStart(d: Date): number {
  return (d.getHours() - START_HOUR) * 60 + d.getMinutes();
}

function setMinutesFromStart(base: Date, mins: number): Date {
  const out = new Date(base);
  const total = Math.max(0, Math.min(TOTAL_MIN - 1, mins));
  const snapped = Math.round(total / SNAP_MIN) * SNAP_MIN;
  out.setHours(START_HOUR + Math.floor(snapped / 60), snapped % 60, 0, 0);
  return out;
}

export function EntryTimeEditor({
  entry, dayEntries, onSave, onCancel, onRenameFood, busy,
}: {
  entry: MealEntry;
  dayEntries: MealEntry[];
  onSave: (patch: { ts: string; slot: MealSlot; quantity_g?: number }) => void;
  onCancel: () => void;
  onRenameFood?: (food_id: string, name: string) => Promise<void>;
  busy: boolean;
}) {
  const initial = new Date(entry.ts);
  const [t, setT] = useState<Date>(initial);
  const [slot, setSlot] = useState<MealSlot>(entry.slot);
  const [renaming, setRenaming] = useState(false);
  const [renameValue, setRenameValue] = useState(entry.food_name);
  const [renameBusy, setRenameBusy] = useState(false);
  // Servings as a string so the user can clear/retype freely. Defaults to
  // the current entry's `servings` (e.g. 325 for a buggy entry — they'll
  // immediately see "this is wildly wrong").
  const [servingsStr, setServingsStr] = useState<string>(
    () => String(round2(entry.servings ?? entry.quantity_g / 100)),
  );
  const trackRef = useRef<HTMLDivElement>(null);

  const minsNow = toMinutesFromStart(t);
  const pct = Math.max(0, Math.min(100, (minsNow / TOTAL_MIN) * 100));

  const xToTime = (clientX: number): Date => {
    const rect = trackRef.current?.getBoundingClientRect();
    if (!rect) return t;
    const ratio = (clientX - rect.left) / rect.width;
    const mins = ratio * TOTAL_MIN;
    return setMinutesFromStart(initial, mins);
  };

  // Pointer events: capture on the track so dragging outside still works.
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (busy) return;
    (e.target as Element).setPointerCapture?.(e.pointerId);
    setT(xToTime(e.clientX));
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (busy || e.buttons === 0) return;
    setT(xToTime(e.clientX));
  };

  // Esc to cancel — useful on desktop.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  // Hour ticks (every 4h labelled, every 1h tick).
  const ticks: { hour: number; pct: number; label: boolean }[] = [];
  for (let h = START_HOUR; h <= END_HOUR; h++) {
    const tickMins = (h - START_HOUR) * 60;
    ticks.push({ hour: h, pct: (tickMins / TOTAL_MIN) * 100, label: h % 4 === 0 });
  }

  // Other entries on the same day, plotted as ghost dots so you can see
  // proximity. Skip the one being edited.
  const ghosts = dayEntries.filter(d => d.id !== entry.id).map(d => {
    const dt = new Date(d.ts);
    return {
      id: d.id,
      pct: Math.max(0, Math.min(100, (toMinutesFromStart(dt) / TOTAL_MIN) * 100)),
      isWater: d.food_name === "Water",
    };
  });

  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-700 p-4 space-y-4">
      <div className="flex items-baseline justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="text-xs uppercase tracking-wide text-neutral-400">edit time</div>
          {renaming ? (
            <div className="flex items-center gap-2 mt-1">
              <input
                value={renameValue}
                onChange={e => setRenameValue(e.target.value)}
                disabled={renameBusy || busy}
                autoFocus
                className="flex-1 min-w-0 px-2 py-2 rounded bg-neutral-800 border border-neutral-700 text-base"
                aria-label="food name"
              />
              <button
                onClick={async () => {
                  if (!onRenameFood) return;
                  const next = renameValue.trim();
                  if (!next || next === entry.food_name) {
                    setRenaming(false);
                    return;
                  }
                  setRenameBusy(true);
                  try {
                    await onRenameFood(entry.food_id, next);
                    setRenaming(false);
                  } finally {
                    setRenameBusy(false);
                  }
                }}
                disabled={renameBusy || busy || !renameValue.trim()}
                className="px-3 py-2 rounded bg-emerald-700 active:bg-emerald-800 text-white text-sm disabled:opacity-50"
              >
                {renameBusy ? "..." : "save"}
              </button>
              <button
                onClick={() => { setRenaming(false); setRenameValue(entry.food_name); }}
                disabled={renameBusy}
                className="px-2 py-2 text-neutral-400 text-sm"
                aria-label="cancel rename"
              >
                ✕
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <div className="font-medium truncate">{entry.food_name}</div>
              {onRenameFood && (
                <button
                  onClick={() => { setRenameValue(entry.food_name); setRenaming(true); }}
                  className="text-neutral-500 active:text-neutral-200 text-sm px-1"
                  aria-label="rename food"
                  title="rename food (cascades to all entries)"
                >
                  ✎
                </button>
              )}
            </div>
          )}
        </div>
        <div className="text-2xl font-semibold tabular-nums text-emerald-300">
          {fmtTime(t)}
        </div>
      </div>

      {/* Quantity */}
      <QuantityField
        entry={entry}
        servingsStr={servingsStr}
        onServingsStr={setServingsStr}
        busy={busy}
      />

      {/* Slot chips */}
      <div className="flex flex-wrap gap-2">
        {SLOTS.map(s => (
          <button
            key={s}
            onClick={() => setSlot(s)}
            disabled={busy}
            className={`px-3 py-2 rounded-full text-sm min-h-[44px] capitalize ${
              slot === s
                ? "bg-emerald-700 text-white"
                : "bg-neutral-800 active:bg-neutral-700 text-neutral-300"
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {/* Day strip */}
      <div className="select-none">
        <div
          ref={trackRef}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          className="relative h-16 rounded-lg bg-neutral-800 touch-none cursor-pointer"
        >
          {/* hour ticks */}
          {ticks.map(tk => (
            <div
              key={tk.hour}
              className={`absolute top-0 bottom-0 w-px ${tk.label ? "bg-neutral-600" : "bg-neutral-700"}`}
              style={{ left: `${tk.pct}%` }}
            />
          ))}
          {/* ghost entries */}
          {ghosts.map(g => (
            <div
              key={g.id}
              className={`absolute top-1/2 -translate-y-1/2 w-2 h-2 rounded-full ${
                g.isWater ? "bg-sky-700" : "bg-neutral-500"
              } opacity-60`}
              style={{ left: `${g.pct}%`, transform: "translate(-50%, -50%)" }}
            />
          ))}
          {/* draggable thumb */}
          <div
            className="absolute top-0 bottom-0 w-1 bg-emerald-400"
            style={{ left: `${pct}%`, transform: "translateX(-50%)" }}
          />
          <div
            className="absolute top-1/2 w-7 h-7 rounded-full bg-emerald-500 border-2 border-emerald-200 shadow-lg"
            style={{ left: `${pct}%`, transform: "translate(-50%, -50%)" }}
          />
        </div>
        {/* hour labels */}
        <div className="relative h-4 mt-1 text-[10px] text-neutral-500">
          {ticks.filter(t => t.label).map(tk => (
            <div
              key={tk.hour}
              className="absolute"
              style={{ left: `${tk.pct}%`, transform: "translateX(-50%)" }}
            >
              {tk.hour === 24 ? "12a" : tk.hour === 12 ? "12p" : tk.hour > 12 ? `${tk.hour - 12}p` : `${tk.hour}a`}
            </div>
          ))}
        </div>
      </div>

      <div className="flex gap-2">
        <button
          onClick={() => onSave(buildPatch(entry, t, slot, servingsStr))}
          disabled={busy || !isValidServings(servingsStr)}
          className="flex-1 px-3 py-3 rounded bg-emerald-700 active:bg-emerald-800 text-white text-base font-medium disabled:opacity-50 min-h-[44px]"
        >
          {busy ? "saving..." : "save"}
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
