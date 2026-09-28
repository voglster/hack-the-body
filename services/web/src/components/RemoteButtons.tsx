import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { ButtonAction, Food, RemoteButton } from "../api/types";
import { ACTION_LABEL, DEFAULT_WATER_OZ, describeButton, mappingFor } from "../lib/remoteButtons";

const REMOTE = "habit_remote_1";
const POSITIONS = ["up", "left", "center", "right", "down"] as const;
type Position = (typeof POSITIONS)[number];
const GRID_AREA: Record<Position, string> = {
  up: "col-start-2 row-start-1", left: "col-start-1 row-start-2", center: "col-start-2 row-start-2",
  right: "col-start-3 row-start-2", down: "col-start-2 row-start-3",
};
// U+FE0E asks for text presentation; without it ◀/▶ render as colour emoji beside plain ▲/▼.
const TEXT = "\uFE0E";
const ARROW: Record<Position, string> = {
  up: `▲${TEXT}`, left: `◀${TEXT}`, center: "●", right: `▶${TEXT}`, down: `▼${TEXT}`,
};
/** The IKEA remote, drawn as it sits in the hand; tap a button to change it. */
export function RemoteButtons() {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<Position | null>(null);
  const buttons = useQuery({ queryKey: ["remote-buttons"], queryFn: api.remoteButtons, enabled: open });
  const byPosition = new Map((buttons.data ?? []).map((b) => [b.button.split("/")[1], b]));

  return (
    <section className="mt-8">
      <button onClick={() => setOpen((v) => !v)} className="text-xs uppercase tracking-wide text-neutral-500">
        {open ? "▾" : "▸"} Remote buttons
      </button>
      {open && (
        <div className="mt-3 flex flex-col gap-4">
          <div className="grid grid-cols-3 grid-rows-3 gap-2 max-w-sm">
            {POSITIONS.map((pos) => (
              <button
                key={pos}
                onClick={() => setEditing(pos)}
                className={`${GRID_AREA[pos]} rounded-xl border px-2 py-3 text-sm leading-tight ${
                  editing === pos ? "border-emerald-500 bg-emerald-950/40" : "border-neutral-700 bg-neutral-900"
                }`}
              >
                <span className="block text-neutral-500">{ARROW[pos]}</span>
                {describeButton(byPosition.get(pos))}
              </button>
            ))}
          </div>
          {editing && (
            <ButtonEditor
              key={editing}
              position={editing}
              current={byPosition.get(editing)}
              onDone={() => setEditing(null)}
            />
          )}
        </div>
      )}
    </section>
  );
}

function ButtonEditor({ position, current, onDone }: {
  position: Position; current: RemoteButton | undefined; onDone: () => void;
}) {
  const qc = useQueryClient();
  const [action, setAction] = useState<ButtonAction>(current?.action ?? "food");
  const [oz, setOz] = useState(String(current?.oz ?? DEFAULT_WATER_OZ));
  const [query, setQuery] = useState("");
  const [food, setFood] = useState<{ id: string; name: string; quantity_g: number } | null>(
    current?.action === "food" && current.food_id
      ? { id: current.food_id, name: current.label, quantity_g: current.quantity_g ?? 100 } : null,
  );
  const results = useQuery({
    queryKey: ["food-search", query],
    queryFn: () => api.searchFoods(query, 6),
    enabled: action === "food" && query.trim().length >= 2,
  });
  const save = useMutation({
    mutationFn: api.setRemoteButton,
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["remote-buttons"] }); onDone(); },
  });

  const draft = mappingFor(`${REMOTE}/${position}`, { action, oz, food });

  const pick = (f: Food) => {
    setFood({ id: f.id, name: f.name, quantity_g: f.serving_g });
    setQuery("");
  };

  return (
    <div className="rounded-2xl border border-neutral-700 bg-neutral-900 p-3 flex flex-col gap-3 max-w-sm">
      <div className="text-sm text-neutral-400">{ARROW[position]} {position} does:</div>
      <div className="flex flex-wrap gap-2">
        {(Object.keys(ACTION_LABEL) as ButtonAction[]).map((a) => (
          <button key={a} onClick={() => setAction(a)}
                  className={`rounded-full px-3 py-1 border ${action === a ? "border-emerald-500 text-emerald-300" : "border-neutral-700"}`}>
            {ACTION_LABEL[a]}
          </button>
        ))}
      </div>
      {action === "water" && (
        <label className="text-sm text-neutral-400">
          ounces per press{" "}
          <input value={oz} onChange={(e) => setOz(e.target.value)} inputMode="numeric"
                 className="w-20 rounded bg-neutral-800 border border-neutral-700 px-2 py-1" />
        </label>
      )}
      {action === "food" && (
        <div className="flex flex-col gap-2">
          {food && <div className="text-emerald-300">✓ {food.name}</div>}
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search your foods"
                 className="rounded bg-neutral-800 border border-neutral-700 px-3 py-2" />
          {(results.data ?? []).map((f) => (
            <button key={f.id} onClick={() => pick(f)} className="text-left rounded px-2 py-1 bg-neutral-800">
              {f.name}
            </button>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <button onClick={() => { if (draft) save.mutate(draft); }} disabled={save.isPending || !draft}
                className="rounded-xl bg-emerald-700 px-4 py-2 disabled:opacity-50">Save</button>
        <button onClick={onDone} className="rounded-xl bg-neutral-800 px-4 py-2">Cancel</button>
      </div>
    </div>
  );
}
