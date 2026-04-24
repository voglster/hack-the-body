import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, } from "recharts";
import { api } from "../api/client";
import { kgToLbs } from "../lib/format";
import { rollingAverage } from "../lib/trend";
export function WeightChart() {
    const { data } = useQuery({
        queryKey: ["weightRange", 60],
        queryFn: () => api.weightRange(60),
    });
    if (!data?.length)
        return _jsx("div", { className: "text-neutral-500", children: "no weight data yet" });
    const pts = data.map(d => ({ ts: d.ts, value: kgToLbs(d.kg) }));
    const smoothed = rollingAverage(pts, 7).map(p => ({
        ts: p.ts.slice(0, 10),
        weight: Number(p.value.toFixed(1)),
        avg7: Number(p.avg.toFixed(1)),
    }));
    return (_jsx("div", { className: "h-64", children: _jsx(ResponsiveContainer, { children: _jsxs(LineChart, { data: smoothed, children: [_jsx(CartesianGrid, { stroke: "#262626" }), _jsx(XAxis, { dataKey: "ts", stroke: "#737373", fontSize: 11 }), _jsx(YAxis, { stroke: "#737373", domain: ["dataMin - 2", "dataMax + 2"], fontSize: 11 }), _jsx(Tooltip, { contentStyle: { background: "#0a0a0a", border: "1px solid #262626" } }), _jsx(Line, { type: "monotone", dataKey: "weight", stroke: "#a3a3a3", dot: false, strokeWidth: 1 }), _jsx(Line, { type: "monotone", dataKey: "avg7", stroke: "#22d3ee", dot: false, strokeWidth: 2 })] }) }) }));
}
