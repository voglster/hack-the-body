import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
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
      <DayBars data={data} loading={isLoading} day={day} isToday={isToday} />
    </div>
  );
}

/** Find the slot index in the 24h grid for the given timestamp (ms or Date).
 *  Returns -1 if outside the day window. */
function slotIndex(rows: { sortKey: number }[], at: number): number {
  if (rows.length === 0) return -1;
  const slotStart = at - (at % (15 * 60_000));
  // sortKey of grid row N is local-midnight + N*15min, but since the grid is
  // built in local tz with Date(y,m,d,0,i*15) we can match exactly.
  for (let i = 0; i < rows.length; i++) {
    if (rows[i].sortKey === slotStart) return i;
  }
  // Fall back: clamp to last index if `at` is past end-of-day.
  if (at >= rows[rows.length - 1].sortKey + 15 * 60_000) return rows.length - 1;
  return -1;
}

function lastSyncedTs(buckets: { ts: string; steps: number }[]): number | null {
  if (!buckets || buckets.length === 0) return null;
  let latest = 0;
  for (const b of buckets) {
    const t = new Date(b.ts).getTime();
    if (t > latest) latest = t;
  }
  return latest || null;
}

function formatLagMin(min: number): string {
  if (min < 1) return "live";
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m === 0 ? `${h}h` : `${h}h${m}m`;
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

interface Markers {
  rows: ReturnType<typeof buildDayGrid>;
  nowIdx: number;
  lastIdx: number;
  showLastSync: boolean;
  lagMin: number | null;
}

function computeMarkers(
  rows: ReturnType<typeof buildDayGrid>,
  buckets: { ts: string; steps: number }[],
  now: number,
  isToday: boolean,
): Markers {
  const nowIdx = isToday ? slotIndex(rows, now) : -1;
  const lastTs = isToday ? lastSyncedTs(buckets) : null;
  const lastIdx = lastTs != null ? slotIndex(rows, lastTs) : -1;
  const showLastSync = lastIdx >= 0 && (nowIdx < 0 || lastIdx < nowIdx);
  const lagMin = lastTs != null && isToday
    ? Math.max(0, Math.round((now - lastTs) / 60_000))
    : null;
  return { rows, nowIdx, lastIdx, showLastSync, lagMin };
}

function DayBars({
  data, loading, day, isToday,
}: {
  data: { buckets: { ts: string; steps: number }[]; total: number } | undefined;
  loading: boolean;
  day: string;
  isToday: boolean;
}) {
  // `now` ticks every 30s so the "now" reference line marches in real time.
  const now = useNow(30_000);
  if (loading) return <div className="h-48 text-neutral-500 text-sm">loading...</div>;
  const rows = buildDayGrid(day, data?.buckets ?? []);
  const m = computeMarkers(rows, data?.buckets ?? [], now, isToday);

  return (
    <div className="space-y-1">
      <div className="h-48">
        <ResponsiveContainer>
          <BarChart data={rows}>
            <CartesianGrid stroke="#262626" />
            <XAxis dataKey="hh" stroke="#737373" fontSize={10} interval={15} />
            <YAxis stroke="#737373" fontSize={11} />
            <Tooltip contentStyle={{ background: "#0a0a0a", border: "1px solid #262626" }} />
            <Bar dataKey="steps" fill="#34d399" />
            {m.showLastSync && (
              <ReferenceLine
                x={rows[m.lastIdx].hh}
                stroke="#fbbf24"
                strokeDasharray="3 3"
                strokeWidth={1.5}
                label={{ value: "synced", position: "top", fill: "#fbbf24", fontSize: 10 }}
              />
            )}
            {m.nowIdx >= 0 && (
              <ReferenceLine
                x={rows[m.nowIdx].hh}
                stroke="#e5e5e5"
                strokeWidth={1.5}
                label={{ value: "now", position: "top", fill: "#e5e5e5", fontSize: 10 }}
              />
            )}
          </BarChart>
        </ResponsiveContainer>
      </div>
      {isToday && <SyncLegend showLastSync={m.showLastSync} lagMin={m.lagMin} />}
    </div>
  );
}

function SyncLegend({ showLastSync, lagMin }: { showLastSync: boolean; lagMin: number | null }) {
  return (
    <div className="flex items-center justify-end gap-3 text-[10px] text-neutral-500 px-1">
      {showLastSync && lagMin != null ? (
        <>
          <LegendDot color="#fbbf24" dashed /> last sync · {formatLagMin(lagMin)} ago
          <LegendDot color="#e5e5e5" /> now
        </>
      ) : (
        <><LegendDot color="#e5e5e5" /> now {lagMin === 0 && "· live"}</>
      )}
    </div>
  );
}

/** Re-renders the caller every `intervalMs` so time-based UI (e.g. a "now"
 *  reference line) advances without being marked impure by lint rules. */
function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return now;
}

function LegendDot({ color, dashed }: { color: string; dashed?: boolean }) {
  return (
    <span
      aria-hidden
      className="inline-block w-3 h-0 align-middle mr-0.5"
      style={{
        borderTop: `1.5px ${dashed ? "dashed" : "solid"} ${color}`,
      }}
    />
  );
}
