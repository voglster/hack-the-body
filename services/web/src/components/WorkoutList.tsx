import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { formatDuration } from "../lib/format";

export function WorkoutList() {
  const { data } = useQuery({
    queryKey: ["workouts", 14],
    queryFn: () => api.workouts(14),
  });
  if (!data?.length) return <div className="text-neutral-500">no workouts logged yet</div>;

  return (
    <ul className="divide-y divide-neutral-800">
      {data.map(w => (
        <li key={w.source_id} className="py-2 flex justify-between gap-4">
          <div>
            <div className="font-medium capitalize">{w.activity_type.replace(/_/g, " ")}</div>
            <div className="text-xs text-neutral-500">{w.ts.slice(0, 16).replace("T", " ")}</div>
          </div>
          <div className="text-right text-sm">
            <div>{formatDuration(w.duration_s)}</div>
            {w.distance_m != null && (
              <div className="text-neutral-500">{(w.distance_m / 1000).toFixed(2)} km</div>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
