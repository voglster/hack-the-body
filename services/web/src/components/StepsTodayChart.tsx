import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { api } from "../api/client";
import { formatLocalDay, localDayBoundsUTC, shiftLocalISO, todayLocalISO } from "../lib/tz";

interface DayChartProps {
  /** Optional callback so the parent can stay in sync with the browsed day. */
  onDayChange?: (localISO: string) => void;
}

/**
 * Intraday step chart for a single browser-local day, with prev/next/today
 * navigation. Emits the active day to the parent via onDayChange so e.g. the
 * Steps card can show that day's total instead of always today's.
 */
export function StepsTodayChart({ onDayChange }: DayChartProps) {
  const [day, setDay] = useState<string>(todayLocalISO());
  const isToday = day === todayLocalISO();

  const setAndEmit = (next: string) => {
    setDay(next);
    onDayChange?.(next);
  };

  const { start, end } = localDayBoundsUTC(day);
  const { data, isLoading } = useQuery({
    queryKey: ["stepsDay", day],
    queryFn: () => api.stepsDay(start, end),
    refetchInterval: isToday ? 60_000 : false,
  });

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-sm">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setAndEmit(shiftLocalISO(day, -1))}
            className="px-2 py-0.5 rounded bg-neutral-800 hover:bg-neutral-700"
          >
            ‹
          </button>
          <span className="tabular-nums">{formatLocalDay(day)}</span>
          <button
            onClick={() => setAndEmit(shiftLocalISO(day, 1))}
            disabled={isToday}
            className="px-2 py-0.5 rounded bg-neutral-800 hover:bg-neutral-700 disabled:opacity-30"
          >
            ›
          </button>
          {!isToday && (
            <button
              onClick={() => setAndEmit(todayLocalISO())}
              className="ml-2 px-2 py-0.5 rounded bg-neutral-800 hover:bg-neutral-700 text-xs"
            >
              today
            </button>
          )}
        </div>
        <div className="text-neutral-400 tabular-nums">
          {data ? `${data.total.toLocaleString()} steps` : ""}
        </div>
      </div>
      <DayBars data={data} loading={isLoading} />
    </div>
  );
}

function DayBars({
  data, loading,
}: {
  data: { buckets: { ts: string; steps: number }[]; total: number } | undefined;
  loading: boolean;
}) {
  if (loading) return <div className="h-48 text-neutral-500 text-sm">loading...</div>;
  if (!data?.buckets.length) {
    return <div className="h-48 text-neutral-500 text-sm">no intraday step data for this day</div>;
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
