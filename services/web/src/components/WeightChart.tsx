import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { api } from "../api/client";
import { kgToLbs } from "../lib/format";
import { rollingAverage } from "../lib/trend";

export function WeightChart() {
  const { data } = useQuery({
    queryKey: ["weightRange", 60],
    queryFn: () => api.weightRange(60),
  });
  if (!data?.length) return <div className="text-neutral-500">no weight data yet</div>;

  const pts = data.map(d => ({ ts: d.ts, value: kgToLbs(d.kg) }));
  const smoothed = rollingAverage(pts, 7).map(p => ({
    t: new Date(p.ts).getTime(),
    weight: Number(p.value.toFixed(1)),
    avg7: Number(p.avg.toFixed(1)),
  }));

  const fmtTick = (ms: number) => {
    const d = new Date(ms);
    return `${d.getMonth() + 1}/${d.getDate()}`;
  };
  const fmtTooltip = (ms: unknown) =>
    typeof ms === "number" ? new Date(ms).toLocaleString() : "";

  return (
    <div className="h-64">
      <ResponsiveContainer>
        <LineChart data={smoothed}>
          <CartesianGrid stroke="#262626" />
          <XAxis
            dataKey="t"
            type="number"
            scale="time"
            domain={["dataMin", "dataMax"]}
            tickFormatter={fmtTick}
            stroke="#737373"
            fontSize={11}
          />
          <YAxis stroke="#737373" domain={["dataMin - 2", "dataMax + 2"]} fontSize={11} />
          <Tooltip
            contentStyle={{ background: "#0a0a0a", border: "1px solid #262626" }}
            labelFormatter={fmtTooltip}
          />
          <Line type="monotone" dataKey="weight" stroke="#a3a3a3" dot={false} strokeWidth={1} />
          <Line type="monotone" dataKey="avg7" stroke="#22d3ee" dot={false} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
