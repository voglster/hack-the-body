import { useQuery } from "@tanstack/react-query";
import {
  Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { api } from "../api/client";

export function StepsChart() {
  const { data } = useQuery({
    queryKey: ["stepsRange", 30],
    queryFn: () => api.stepsRange(30),
  });
  if (!data?.length) return <div className="text-neutral-500">no step data yet</div>;

  const rows = data.map(d => ({
    ts: d.ts.slice(0, 10),
    steps: d.steps,
  }));
  const goal = data[data.length - 1]?.step_goal ?? null;

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
