import { jsx as _jsx, jsxs as _jsxs } from "react/jsx-runtime";
export function MetricCard({ label, value, sub }) {
    return (_jsxs("div", { className: "rounded-xl bg-neutral-900 border border-neutral-800 p-4 flex flex-col gap-1", children: [_jsx("div", { className: "text-xs uppercase tracking-wide text-neutral-400", children: label }), _jsx("div", { className: "text-3xl font-semibold tabular-nums", children: value }), sub && _jsx("div", { className: "text-xs text-neutral-500", children: sub })] }));
}
