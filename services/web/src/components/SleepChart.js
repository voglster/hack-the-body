import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useQuery } from "@tanstack/react-query";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis, } from "recharts";
import { api } from "../api/client";
export function SleepChart() {
    const { data } = useQuery({
        queryKey: ["sleepRange", 30],
        queryFn: () => api.sleepRange(30),
    });
    if (!data?.length)
        return _jsx("div", { className: "text-neutral-500", children: "no sleep data yet" });
    const rows = data.map(s => ({
        ts: s.ts.slice(0, 10),
        hours: Number((s.duration_s / 3600).toFixed(2)),
    }));
    return (_jsx("div", { className: "h-64", children: _jsx(ResponsiveContainer, { children: _jsxs(BarChart, { data: rows, children: [_jsx(CartesianGrid, { stroke: "#262626" }), _jsx(XAxis, { dataKey: "ts", stroke: "#737373", fontSize: 11 }), _jsx(YAxis, { stroke: "#737373", domain: [0, 10], fontSize: 11 }), _jsx(Tooltip, { contentStyle: { background: "#0a0a0a", border: "1px solid #262626" } }), _jsx(Bar, { dataKey: "hours", fill: "#818cf8" })] }) }) }));
}
