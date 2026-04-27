import { useQuery } from "@tanstack/react-query";
import {
  Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { api } from "../api/client";

export function SleepChart() {
  const { data } = useQuery({
    queryKey: ["sleepRange", 30],
    queryFn: () => api.sleepRange(30),
  });
  if (!data?.length) return <div className="text-neutral-500">no sleep data yet</div>;

  const rows = data.map(s => ({
    ts: s.ts.slice(0, 10),
    hours: Number((s.duration_s / 3600).toFixed(2)),
  }));

  return (
    <div className="h-64">
      <ResponsiveContainer>
        <BarChart data={rows}>
          <CartesianGrid stroke="#262626" />
          <XAxis dataKey="ts" stroke="#737373" fontSize={11} />
          <YAxis stroke="#737373" domain={[0, 10]} fontSize={11} />
          <Tooltip contentStyle={{ background: "#0a0a0a", border: "1px solid #262626" }} />
          <Bar dataKey="hours" fill="#818cf8" />
          <ReferenceLine
            y={8}
            stroke="#34d399"
            strokeDasharray="4 4"
            label={{ value: "8h", position: "right", fill: "#34d399", fontSize: 11 }}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
