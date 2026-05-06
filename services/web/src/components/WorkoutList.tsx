import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { WorkoutListRow } from "./WorkoutListRow";

export function WorkoutList() {
  const { data } = useQuery({
    queryKey: ["workouts", 14],
    queryFn: () => api.workouts(14),
  });
  if (!data?.length) return <div className="text-neutral-500">no workouts logged yet</div>;

  return (
    <div className="flex flex-col gap-2">
      {data.map(w => <WorkoutListRow key={w.source_id} workout={w} />)}
    </div>
  );
}
