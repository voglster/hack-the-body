import { Link } from "react-router-dom";

import type { Workout } from "../api/types";

const ICON: Record<string, string> = {
  strength: "🏋",
  treadmill: "🏃",
  running: "🏃",
  walking: "🚶",
  cycling: "🚴",
};

function fmtDuration(seconds: number): string {
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m}min`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem ? `${h}h${rem}m` : `${h}h`;
}

function fmtDistance(meters?: number | null): string | null {
  if (meters == null) return null;
  const mi = meters / 1609.344;
  return mi >= 0.1 ? `${mi.toFixed(1)}mi` : `${Math.round(meters)}m`;
}

export function WorkoutListRow({ workout }: { workout: Workout }) {
  const icon = ICON[workout.activity_type] ?? "💪";
  const isStrength = workout.activity_type === "strength";
  const title = workout.title ?? workout.activity_type;
  const dur = fmtDuration(workout.duration_s);
  const right = isStrength
    ? `${workout.exercise_count ?? 0} ex · ${workout.set_count ?? 0} sets`
    : (fmtDistance(workout.distance_m) ?? "");

  return (
    <Link
      to={`/workouts/${encodeURIComponent(workout.source_id)}`}
      className="flex items-center gap-3 px-3 py-3 rounded-xl bg-neutral-900/50 active:bg-neutral-900"
    >
      <span className="text-2xl shrink-0">{icon}</span>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium truncate">{title}</div>
        <div className="text-xs text-neutral-400">
          {dur}{right ? ` · ${right}` : ""}
        </div>
      </div>
      <span className="text-neutral-600">›</span>
    </Link>
  );
}
