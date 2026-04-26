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
      <DayBars data={data} loading={isLoading} day={day} />
    </div>
  );
}

/** Build an empty 24-hour grid in 15-min buckets for the given local day,
 *  then overlay the actual step buckets onto it. Returns 96 rows starting
 *  at local midnight, so the chart x-axis is always 0..24h regardless of
 *  whether the day has finished. */
function buildDayGrid(
  localDayISO: string,
  buckets: { ts: string; steps: number }[],
): { hh: string; steps: number; sortKey: number }[] {
  const [y, m, d] = localDayISO.split("-").map(Number);
  const grid: { hh: string; steps: number; sortKey: number }[] = [];
  for (let i = 0; i < 96; i++) {
    const dt = new Date(y, m - 1, d, 0, i * 15);
    const label = dt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    grid.push({ hh: label, steps: 0, sortKey: dt.getTime() });
  }
  // Merge actual buckets by nearest 15-min slot start (local).
  for (const b of buckets) {
    const t = new Date(b.ts);
    const slotStart = new Date(t);
    slotStart.setMinutes(Math.floor(slotStart.getMinutes() / 15) * 15, 0, 0);
    const idx = grid.findIndex(g => g.sortKey === slotStart.getTime());
    if (idx >= 0) grid[idx].steps += b.steps;
  }
  return grid;
}

function DayBars({
  data, loading, day,
}: {
  data: { buckets: { ts: string; steps: number }[]; total: number } | undefined;
  loading: boolean;
  day: string;
}) {
  if (loading) return <div className="h-48 text-neutral-500 text-sm">loading...</div>;
  // Even with no data yet, render the empty 24h grid so the user sees the
  // shape they're filling in.
  const rows = buildDayGrid(day, data?.buckets ?? []);
  return (
    <div className="h-48">
      <ResponsiveContainer>
        <BarChart data={rows}>
          <CartesianGrid stroke="#262626" />
          <XAxis dataKey="hh" stroke="#737373" fontSize={10} interval={15} />
          <YAxis stroke="#737373" fontSize={11} />
          <Tooltip contentStyle={{ background: "#0a0a0a", border: "1px solid #262626" }} />
          <Bar dataKey="steps" fill="#34d399" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
