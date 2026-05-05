import type { StrengthSetView, WorkoutDetailExercise } from "../api/types";

function formatSet(s: StrengthSetView): string {
  const parts: string[] = [];
  if (s.weight_kg != null) parts.push(`${s.weight_kg}kg`);
  if (s.reps != null) parts.push(`${s.reps} reps`);
  if (s.duration_s != null) parts.push(`${s.duration_s}s`);
  if (s.distance_m != null) parts.push(`${s.distance_m}m`);
  const body = parts.join(" × ");
  if (s.set_type && s.set_type !== "normal") {
    return `${body} (${s.set_type})`;
  }
  return body || "—";
}

export function StrengthSetTable({ exercises }: { exercises: WorkoutDetailExercise[] }) {
  return (
    <div className="flex flex-col gap-4">
      {exercises.map((ex) => (
        <div key={`${ex.index}-${ex.title}`} className="bg-neutral-900/50 rounded-xl p-3">
          <div className="flex items-baseline justify-between mb-2">
            <h3 className="text-sm font-medium">{ex.title}</h3>
            <span className="text-xs text-neutral-500">{ex.sets.length} sets</span>
          </div>
          <div className="flex flex-col gap-1">
            {ex.sets.map((s) => (
              <div key={s.set_index} className="flex items-center gap-3 text-sm font-mono">
                <span className="text-neutral-500 w-4 text-right">{s.set_index + 1}</span>
                <span className="flex-1">{formatSet(s)}</span>
                {s.rpe != null && (
                  <span className="text-xs text-amber-300">RPE {s.rpe}</span>
                )}
              </div>
            ))}
          </div>
          {ex.notes && (
            <div className="mt-2 text-xs text-neutral-500 italic">{ex.notes}</div>
          )}
        </div>
      ))}
    </div>
  );
}
