import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { api } from "../api/client";

export function HrvChart() {
  const { data } = useQuery({
    queryKey: ["hrvRange", 30],
    queryFn: () => api.hrvRange(30),
  });
  if (!data?.length) return <div className="text-neutral-500">no HRV data yet</div>;

  const rows = data.map(h => ({
    ts: h.ts.slice(0, 10),
    rmssd: Number(h.rmssd_ms.toFixed(1)),
  }));

  return (
    <div className="h-64">
      <ResponsiveContainer>
        <LineChart data={rows}>
          <CartesianGrid stroke="#262626" />
          <XAxis dataKey="ts" stroke="#737373" fontSize={11} />
          <YAxis stroke="#737373" fontSize={11} />
          <Tooltip contentStyle={{ background: "#0a0a0a", border: "1px solid #262626" }} />
          <Line type="monotone" dataKey="rmssd" stroke="#f472b6" dot={false} strokeWidth={2} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
