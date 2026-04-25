import { useQuery } from "@tanstack/react-query";
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { api } from "../api/client";

export function StepsTodayChart() {
  const { data } = useQuery({
    queryKey: ["stepsToday.chart"],
    queryFn: api.stepsToday,
    refetchInterval: 60_000,
  });
  if (!data?.buckets.length) {
    return <div className="text-neutral-500">no intraday step data yet today</div>;
  }
  const rows = data.buckets.map(b => ({
    hh: new Date(b.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    steps: b.steps,
  }));
  return (
    <div className="h-48">
      <ResponsiveContainer>
        <BarChart data={rows}>
          <CartesianGrid stroke="#262626" />
          <XAxis dataKey="hh" stroke="#737373" fontSize={10} interval={3} />
          <YAxis stroke="#737373" fontSize={11} />
          <Tooltip contentStyle={{ background: "#0a0a0a", border: "1px solid #262626" }} />
          <Bar dataKey="steps" fill="#34d399" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
