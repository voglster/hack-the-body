/**
 * Water — three states.
 *  - active   : under goal → full card with progress bar + quick buttons
 *  - met      : ≥ daily goal → small one-line pill ("✓ 102 oz"), tap to
 *               re-expand if the user wants to log more
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";

const QUICK_OZ = [8, 12, 16, 20];
/** Fallback when /profile/targets has no daily_water_oz set (cold-start
 *  users). 100 oz is the IOM-style "drinking water from beverages"
 *  baseline — sensible default until the user picks one. */
const DEFAULT_GOAL_OZ = 100;

export function WaterCard() {
  const qc = useQueryClient();
  const today = useQuery({
    queryKey: ["water.today"],
    queryFn: api.waterToday,
    refetchInterval: 60_000,
  });
  const targets = useQuery({
    queryKey: ["profile.targets"],
    queryFn: api.getTargets,
  });
  const log = useMutation({
    mutationFn: (oz: number) => api.logWater(oz),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["water.today"] });
      void qc.invalidateQueries({ queryKey: ["meals.today.entries"] });
      void qc.invalidateQueries({ queryKey: ["meals.today.totals"] });
      void qc.invalidateQueries({ queryKey: ["nudges"] });
    },
  });
  const [forceExpanded, setForceExpanded] = useState(false);

  const oz = today.data?.oz ?? 0;
  const goal = targets.data?.daily_water_oz ?? DEFAULT_GOAL_OZ;
  const fraction = Math.min(1, oz / goal);
  const goalMet = oz >= goal;

  if (goalMet && !forceExpanded) {
    return (
      <button
        onClick={() => setForceExpanded(true)}
        className="w-full text-left text-xs text-neutral-500 hover:text-neutral-300 px-3 py-2 rounded-lg bg-neutral-900/40 border border-neutral-900"
      >
        ✓ water · {oz.toFixed(0)} oz
      </button>
    );
  }

  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-4 space-y-3">
      <div className="flex items-baseline justify-between">
        <div>
          <div className="text-xs uppercase tracking-wide text-neutral-400">Water</div>
          <div className="text-2xl font-semibold tabular-nums">
            {oz.toFixed(0)} <span className="text-sm font-normal text-neutral-500">/ {goal} oz</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="text-xs text-neutral-500 tabular-nums">
            {Math.round(fraction * 100)}%
          </div>
          {goalMet && forceExpanded && (
            <button
              onClick={() => setForceExpanded(false)}
              className="text-xs text-neutral-500 px-2 py-1"
              aria-label="collapse"
            >
              ✕
            </button>
          )}
        </div>
      </div>
      <div className="h-1.5 w-full rounded-full bg-neutral-800 overflow-hidden">
        <div
          className="h-full bg-sky-500"
          style={{ width: `${fraction * 100}%` }}
        />
      </div>
      <div className="flex flex-wrap gap-2">
        {QUICK_OZ.map(n => (
          <button
            key={n}
            onClick={() => log.mutate(n)}
            disabled={log.isPending}
            className="px-3 py-2 rounded bg-sky-700 active:bg-sky-800 text-sm disabled:opacity-50 min-h-[44px]"
          >
            +{n}oz
          </button>
        ))}
      </div>
    </div>
  );
}
