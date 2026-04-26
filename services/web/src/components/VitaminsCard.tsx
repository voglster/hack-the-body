/**
 * Vitamins, three-state.
 *
 *  - active   : nothing logged today → full card with "took 'em" button
 *  - recent   : just logged in the last 5 min → still full size, ring +
 *               edit affordance so the user can fix the time if they
 *               tapped while eating breakfast 30 min later
 *  - settled  : logged > 5 min ago → small one-line pill, tap to expand
 *               back to recent state for editing
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { MealEntry, MealSlot } from "../api/types";
import { EntryTimeEditor } from "./EntryTimeEditor";

const RECENT_MS = 5 * 60 * 1000;

interface CardView {
  logged: boolean;
  ts: string | null;
  isRecent: boolean;
  isSettled: boolean;
}

function computeView(
  logged: boolean | undefined,
  ts: string | null | undefined,
  forceExpanded: boolean,
): CardView {
  const isLogged = logged ?? false;
  const stamp = ts ?? null;
  const ageMs = stamp ? Date.now() - new Date(stamp).getTime() : Infinity;
  const isRecent = isLogged && ageMs < RECENT_MS;
  const isSettled = isLogged && !isRecent && !forceExpanded;
  return { logged: isLogged, ts: stamp, isRecent, isSettled };
}

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
  // User can pop the pill back open even after the recent window expires.
  const [forceExpanded, setForceExpanded] = useState(false);

  const view = computeView(today.data?.logged, today.data?.first_ts, forceExpanded);
  const allEntries = entries.data ?? [];
  const vitaminEntries = allEntries.filter(
    (e: MealEntry) => e.food_name === "Vitamins",
  );
  const target = vitaminEntries[vitaminEntries.length - 1] ?? null;
  const { logged, ts, isRecent, isSettled } = view;

  if (isSettled) {
    return (
      <SettledPill ts={ts} onExpand={() => setForceExpanded(true)} />
    );
  }

  return (
    <div className={`rounded-xl bg-neutral-900 border border-neutral-800 p-4 space-y-3 ${
      isRecent ? "ring-1 ring-emerald-700/50" : ""
    }`}>
      <CardHeader
        logged={logged}
        ts={ts}
        isRecent={isRecent}
        canEdit={!!target}
        onTapHeader={() => { if (logged && target) setEditing(true); }}
        showCollapse={logged && forceExpanded}
        onCollapse={() => setForceExpanded(false)}
        showLogButton={!logged}
        logging={log.isPending}
        onLog={() => log.mutate()}
      />
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

function SettledPill({ ts, onExpand }: { ts: string | null; onExpand: () => void }) {
  return (
    <button
      onClick={onExpand}
      className="w-full text-left text-xs text-neutral-500 hover:text-neutral-300 px-3 py-2 rounded-lg bg-neutral-900/40 border border-neutral-900"
    >
      ✓ vitamins{ts ? ` · ${fmtTime(ts)}` : ""}
    </button>
  );
}

function CardHeader(p: {
  logged: boolean;
  ts: string | null;
  isRecent: boolean;
  canEdit: boolean;
  onTapHeader: () => void;
  showCollapse: boolean;
  onCollapse: () => void;
  showLogButton: boolean;
  logging: boolean;
  onLog: () => void;
}) {
  return (
    <div className="flex items-center gap-3">
      <button
        onClick={p.onTapHeader}
        disabled={!p.logged || !p.canEdit}
        className="flex-1 min-w-0 text-left active:bg-neutral-800/40 -mx-1 px-1 rounded disabled:cursor-default"
        aria-label={p.logged ? "edit vitamin time" : undefined}
      >
        <div className="text-xs uppercase tracking-wide text-neutral-400">Vitamins</div>
        <div className="text-lg font-semibold">
          {p.logged
            ? <span className="text-emerald-400">✓ taken{p.ts ? ` at ${fmtTime(p.ts)}` : ""}</span>
            : <span className="text-neutral-400">not yet today</span>}
        </div>
        {p.isRecent && (
          <div className="text-[11px] text-neutral-500 mt-0.5">tap to fix the time</div>
        )}
      </button>
      {p.showLogButton && (
        <button
          onClick={p.onLog}
          disabled={p.logging}
          className="px-4 py-3 rounded bg-amber-700 active:bg-amber-800 text-white text-sm font-medium disabled:opacity-50 min-h-[44px]"
        >
          {p.logging ? "..." : "took 'em"}
        </button>
      )}
      {p.showCollapse && (
        <button
          onClick={p.onCollapse}
          className="px-2 py-2 text-xs text-neutral-500"
          aria-label="collapse"
        >
          ✕
        </button>
      )}
    </div>
  );
}
