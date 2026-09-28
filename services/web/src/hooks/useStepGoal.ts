import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Summary } from "../api/types";

/** User-set step_goal_override wins over Garmin's auto-tuned step_goal; null = no goal. */
export function useStepGoal(summary: Summary | undefined): number | null {
  const { data: targets } = useQuery({
    queryKey: ["profile.targets"],
    queryFn: api.getTargets,
  });
  return targets?.step_goal_override ?? summary?.daily_summary?.step_goal ?? null;
}
