import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import type { Workout } from "../api/types";
import { WorkoutListRow } from "../components/WorkoutListRow";

function dayKey(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    weekday: "short", month: "short", day: "numeric",
  });
}

export function WorkoutList() {
  const [rows, setRows] = useState<Workout[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.workouts(30).then(
      (data) => { if (!cancelled) setRows(data); },
      (e) => { if (!cancelled) setError(String(e)); },
    );
    return () => { cancelled = true; };
  }, []);

  if (error) return <div className="p-4 text-rose-400">Failed to load: {error}</div>;
  if (rows === null) return <div className="p-4 text-neutral-500">Loading…</div>;
  if (rows.length === 0) {
    return <div className="p-4 text-neutral-500">No workouts in the last 30 days.</div>;
  }

  const grouped: Array<[string, Workout[]]> = [];
  let last: string | null = null;
  for (const w of rows) {
    const k = dayKey(w.ts);
    if (k !== last) { grouped.push([k, []]); last = k; }
    grouped[grouped.length - 1][1].push(w);
  }

  return (
    <div className="max-w-2xl mx-auto p-4 pb-24">
      <header className="mb-4 flex items-center gap-3">
        <Link to="/more" className="text-neutral-400 active:text-neutral-200">‹ Back</Link>
        <h1 className="text-lg font-semibold">Workouts</h1>
      </header>
      <div className="flex flex-col gap-4">
        {grouped.map(([day, items]) => (
          <section key={day}>
            <h2 className="text-xs uppercase tracking-wide text-neutral-500 mb-2">{day}</h2>
            <div className="flex flex-col gap-2">
              {items.map((w) => <WorkoutListRow key={w.source_id} workout={w} />)}
            </div>
          </section>
        ))}
      </div>
    </div>
  );
}
