import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis, } from "recharts";
import { api } from "../api/client";
export function HrvChart() {
    const { data } = useQuery({
        queryKey: ["hrvRange", 30],
        queryFn: () => api.hrvRange(30),
    });
    if (!data?.length)
        return _jsx("div", { className: "text-neutral-500", children: "no HRV data yet" });
    const rows = data.map(h => ({
        ts: h.ts.slice(0, 10),
        rmssd: Number(h.rmssd_ms.toFixed(1)),
    }));
    return (_jsx("div", { className: "h-64", children: _jsx(ResponsiveContainer, { children: _jsxs(LineChart, { data: rows, children: [_jsx(CartesianGrid, { stroke: "#262626" }), _jsx(XAxis, { dataKey: "ts", stroke: "#737373", fontSize: 11 }), _jsx(YAxis, { stroke: "#737373", fontSize: 11 }), _jsx(Tooltip, { contentStyle: { background: "#0a0a0a", border: "1px solid #262626" } }), _jsx(Line, { type: "monotone", dataKey: "rmssd", stroke: "#f472b6", dot: false, strokeWidth: 2 })] }) }) }));
}
