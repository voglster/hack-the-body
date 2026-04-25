import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { formatDuration } from "../lib/format";
export function WorkoutList() {
    const { data } = useQuery({
        queryKey: ["workouts", 14],
        queryFn: () => api.workouts(14),
    });
    if (!data?.length)
        return _jsx("div", { className: "text-neutral-500", children: "no workouts logged yet" });
    return (_jsx("ul", { className: "divide-y divide-neutral-800", children: data.map(w => (_jsxs("li", { className: "py-2 flex justify-between gap-4", children: [_jsxs("div", { children: [_jsx("div", { className: "font-medium capitalize", children: w.activity_type.replace(/_/g, " ") }), _jsx("div", { className: "text-xs text-neutral-500", children: w.ts.slice(0, 16).replace("T", " ") })] }), _jsxs("div", { className: "text-right text-sm", children: [_jsx("div", { children: formatDuration(w.duration_s) }), w.distance_m != null && (_jsxs("div", { className: "text-neutral-500", children: [(w.distance_m / 1000).toFixed(2), " km"] }))] })] }, w.source_id))) }));
}
