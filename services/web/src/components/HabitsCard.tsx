import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { Habit, HabitStatusToday } from "../api/types";


function statusBadge(s: HabitStatusToday["status"]): string {
  if (s === "done") return "✅";
  if (s === "missed") return "❌";
  if (s === "skipped") return "⏭";
  return "·";  // unknown
}

function HabitRow({ h, onToggle, busy }: {
  h: HabitStatusToday;
  onToggle: (id: string) => void;
  busy: boolean;
}) {
  const isManual = h.kind === "manual";
  const isDone = h.status === "done";
  return (
    <div className="flex items-center justify-between py-2">
      <div>
        <div className="text-sm">{h.name}</div>
        <div className="text-[11px] text-neutral-500">
          {h.kind}{h.resolver ? ` · ${h.resolver}` : ""}
        </div>
      </div>
      <div className="flex items-center gap-2">
        <span className="text-base">{statusBadge(h.status)}</span>
        {isManual && (
          <button
            type="button"
            onClick={() => onToggle(h.id)}
            disabled={busy}
            className={
              "text-xs px-2 py-1 rounded min-h-[32px] " +
              (isDone
                ? "bg-emerald-700 text-white"
                : "bg-neutral-800 active:bg-neutral-700")
            }
          >
            {isDone ? "done" : "mark done"}
          </button>
        )}
      </div>
    </div>
  );
}

function NewHabitForm({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState("");
  const [kind, setKind] = useState<Habit["kind"]>("manual");
  const [resolver, setResolver] = useState("");
  const create = useMutation({
    mutationFn: () =>
      api.habitCreate(name.trim(), kind, resolver.trim() || undefined),
    onSuccess: () => {
      setName(""); setResolver("");
      onCreated();
    },
  });
  return (
    <form
      onSubmit={e => { e.preventDefault(); if (name.trim()) create.mutate(); }}
      className="space-y-2 border-t border-neutral-800 pt-3"
    >
      <div className="text-xs uppercase tracking-wide text-neutral-500">
        Add habit
      </div>
      <div className="flex gap-2">
        <input
          type="text"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="habit name"
          className="flex-1 text-sm px-2 py-2 rounded bg-neutral-800 border border-neutral-700"
        />
        <select
          value={kind}
          onChange={e => setKind(e.target.value as Habit["kind"])}
          className="text-sm px-2 py-2 rounded bg-neutral-800 border border-neutral-700"
        >
          <option value="manual">manual</option>
          <option value="auto">auto</option>
          <option value="none">nudge only</option>
        </select>
      </div>
      {kind === "auto" && (
        <input
          type="text"
          value={resolver}
          onChange={e => setResolver(e.target.value)}
          placeholder="resolver name (e.g. bed_by_10)"
          className="w-full text-sm px-2 py-2 rounded bg-neutral-800 border border-neutral-700"
        />
      )}
      <button
        type="submit"
        disabled={create.isPending || !name.trim() || (kind === "auto" && !resolver.trim())}
        className="text-xs px-3 py-2 rounded bg-emerald-700 active:bg-emerald-800 disabled:opacity-50"
      >
        {create.isPending ? "adding…" : "add habit"}
      </button>
      {create.error && (
        <div className="text-xs text-red-400">{(create.error as Error).message}</div>
      )}
    </form>
  );
}

export function HabitsCard() {
  const qc = useQueryClient();
  const { data: habits = [], isLoading } = useQuery({
    queryKey: ["habits.today"],
    queryFn: api.habitsToday,
  });
  const toggle = useMutation({
    mutationFn: (id: string) => api.habitMarkStatus(id, "done"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["habits.today"] }),
  });
  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-4 space-y-2">
      <div className="text-xs uppercase tracking-wide text-neutral-400">
        Habits
      </div>
      {isLoading ? (
        <div className="text-xs text-neutral-500">loading…</div>
      ) : habits.length === 0 ? (
        <div className="text-xs text-neutral-500">no habits yet — add one below.</div>
      ) : (
        <div className="divide-y divide-neutral-800">
          {habits.map(h => (
            <HabitRow key={h.id} h={h} onToggle={id => toggle.mutate(id)} busy={toggle.isPending} />
          ))}
        </div>
      )}
      <NewHabitForm onCreated={() => qc.invalidateQueries({ queryKey: ["habits.today"] })} />
    </div>
  );
}
