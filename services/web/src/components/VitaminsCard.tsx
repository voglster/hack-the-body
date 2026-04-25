import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { MealEntry, MealSlot } from "../api/types";
import { EntryTimeEditor } from "./EntryTimeEditor";

function fmtTime(iso: string): string {
  const d = new Date(iso);
  const h = d.getHours();
  const m = d.getMinutes().toString().padStart(2, "0");
  const ampm = h >= 12 ? "p" : "a";
  return `${h % 12 === 0 ? 12 : h % 12}:${m}${ampm}`;
}

export function VitaminsCard() {
  const qc = useQueryClient();
  const today = useQuery({
    queryKey: ["vitamins.today"],
    queryFn: api.vitaminsToday,
    refetchInterval: 60_000,
  });
  // Reuse the same cache key TodayMeals uses, so editing here also
  // refreshes the food log section.
  const entries = useQuery({
    queryKey: ["meals.today.entries"],
    queryFn: api.todayEntries,
    refetchInterval: 60_000,
  });

  const invalidateAll = () => {
    void qc.invalidateQueries({ queryKey: ["vitamins.today"] });
    void qc.invalidateQueries({ queryKey: ["meals.today.entries"] });
    void qc.invalidateQueries({ queryKey: ["meals.today.totals"] });
  };

  const log = useMutation({
    mutationFn: api.logVitamins,
    onSuccess: invalidateAll,
  });
  const editEntry = useMutation({
    mutationFn: (args: { id: string; patch: { ts?: string; slot?: MealSlot } }) =>
      api.editEntry(args.id, args.patch),
    onSuccess: invalidateAll,
  });

  const [editing, setEditing] = useState(false);
  const logged = today.data?.logged ?? false;
  const ts = today.data?.first_ts ?? null;

  // Find today's vitamin entry to edit. Prefer the most recent.
  const allEntries = entries.data ?? [];
  const vitaminEntries = allEntries.filter(
    (e: MealEntry) => e.food_name === "Vitamins",
  );
  const target = vitaminEntries[vitaminEntries.length - 1] ?? null;

  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-4 space-y-3">
      <div className="flex items-center gap-3">
        <button
          onClick={() => { if (logged && target) setEditing(true); }}
          disabled={!logged || !target}
          className="flex-1 min-w-0 text-left active:bg-neutral-800/40 -mx-1 px-1 rounded disabled:cursor-default"
          aria-label={logged ? "edit vitamin time" : undefined}
        >
          <div className="text-xs uppercase tracking-wide text-neutral-400">Vitamins</div>
          <div className="text-lg font-semibold">
            {logged
              ? <span className="text-emerald-400">✓ taken{ts ? ` at ${fmtTime(ts)}` : ""}</span>
              : <span className="text-neutral-400">not yet today</span>}
          </div>
        </button>
        {!logged && (
          <button
            onClick={() => log.mutate()}
            disabled={log.isPending}
            className="px-4 py-3 rounded bg-amber-700 active:bg-amber-800 text-white text-sm font-medium disabled:opacity-50 min-h-[44px]"
          >
            {log.isPending ? "..." : "took 'em"}
          </button>
        )}
      </div>

      {editing && target && (
        <EntryTimeEditor
          entry={target}
          dayEntries={allEntries}
          busy={editEntry.isPending}
          onCancel={() => setEditing(false)}
          onSave={(patch) => {
            editEntry.mutate({ id: target.id, patch }, {
              onSuccess: () => setEditing(false),
            });
          }}
        />
      )}
    </div>
  );
}
