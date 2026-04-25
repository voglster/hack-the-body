import { useQuery } from "@tanstack/react-query";
import {
  Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { api } from "../api/client";
import { todayLocalISO } from "../lib/tz";

interface Props {
  /** Current intraday step total for today (browser-local). When provided,
   *  overrides whatever the daily-summary collection has for today — Garmin's
   *  daily summary only finalizes once a day, but the intraday buckets are
   *  fresh every 30 minutes. */
  todayLiveTotal?: number;
}

export function StepsChart({ todayLiveTotal }: Props) {
  const { data } = useQuery({
    queryKey: ["stepsRange", 30],
    queryFn: () => api.stepsRange(30),
  });
  if (!data?.length) return <div className="text-neutral-500">no step data yet</div>;

  const today = todayLocalISO();
  const byDay = new Map<string, number>();
  let goal: number | null = null;
  for (const d of data) {
    const key = d.ts.slice(0, 10);
    byDay.set(key, d.steps);
    if (d.step_goal != null) goal = d.step_goal;
  }
  if (todayLiveTotal != null) {
    const existing = byDay.get(today) ?? 0;
    byDay.set(today, Math.max(existing, todayLiveTotal));
  } else if (!byDay.has(today)) {
    // Even without intraday data, ensure today shows up on the x-axis.
    byDay.set(today, 0);
  }

  const rows = [...byDay.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([ts, steps]) => ({ ts, steps }));

  return (
    <div className="h-64">
      <ResponsiveContainer>
        <BarChart data={rows}>
          <CartesianGrid stroke="#262626" />
          <XAxis dataKey="ts" stroke="#737373" fontSize={11} />
          <YAxis stroke="#737373" fontSize={11} />
          <Tooltip contentStyle={{ background: "#0a0a0a", border: "1px solid #262626" }} />
          <Bar dataKey="steps" fill="#34d399" />
          {goal != null && (
            <ReferenceLine y={goal} stroke="#fbbf24" strokeDasharray="4 4" />
          )}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
