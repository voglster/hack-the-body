/**
 * Presentational live-treadmill view.
 *
 * Renders HeroGauges, CoachingHint, ZoneBars, ChartCard (which polls
 * treadmill samples internally), and StatsGrid. Does NOT include the
 * outer page wrapper or header — the host page handles those.
 */
import { useQuery } from "@tanstack/react-query";
import {
  CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";

import { api } from "../api/client";
import type { ActiveWorkout, TreadmillSample } from "../api/types";
import {
  DEFAULT_TARGET_ZONE, HR_ZONES, zoneAdvice, zoneForHr,
} from "../lib/hrZones";

const SAMPLES_POLL_MS = 5000;

function fmtClock(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`
    : `${m}:${String(r).padStart(2, "0")}`;
}

function elapsedSeconds(startedAtIso: string): number {
  return (Date.now() - new Date(startedAtIso).getTime()) / 1000;
}

function BigStat({ label, value, unit, tone }: {
  label: string; value: string; unit?: string; tone?: string;
}) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-neutral-500">{label}</div>
      <div className={`text-3xl sm:text-4xl font-bold tabular-nums leading-none ${tone ?? ""}`}>
        {value}
      </div>
      {unit && <div className="text-xs text-neutral-500 mt-1">{unit}</div>}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-neutral-500">{label}</div>
      <div className="text-base font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function HeroGauges({ active }: { active: ActiveWorkout }) {
  const speed = active.current_speed_mph ?? active.avg_speed_mph;
  const hr = active.current_hr ?? active.avg_hr;
  const zone = zoneForHr(hr);
  return (
    <section className="rounded-2xl bg-gradient-to-br from-neutral-900 to-neutral-950 border border-emerald-700/40 p-4 sm:p-6 space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-xs uppercase tracking-wider text-emerald-400 flex items-center gap-2">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
          </span>
          <span>Walking — live</span>
        </div>
        <div className="text-[10px] text-neutral-500">{active.sample_count} samples</div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <BigStat label="speed" value={speed.toFixed(1)} unit="mph" tone="text-emerald-300" />
        <BigStat
          label="HR" value={hr != null && hr > 0 ? String(hr) : "—"}
          unit={zone ? zone.label.toLowerCase() : "no strap"}
          tone={zone ? zone.textClass : "text-neutral-400"}
        />
        <BigStat label="time" value={fmtClock(elapsedSeconds(active.started_at))} />
        <BigStat label="distance" value={active.distance_mi.toFixed(2)} unit="mi" />
      </div>
    </section>
  );
}

function ZoneBars({ active }: { active: ActiveWorkout }) {
  const total = Math.max(1, Object.values(active.hr_zones_s).reduce((a, b) => a + b, 0));
  const currentZone = zoneForHr(active.current_hr ?? active.avg_hr);
  return (
    <section className="rounded-2xl bg-neutral-900 border border-neutral-800 p-4 sm:p-6 space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-xs uppercase tracking-wide text-neutral-400">HR zones</div>
        <div className="text-[10px] text-neutral-500">target {DEFAULT_TARGET_ZONE.toUpperCase()} · fat burn</div>
      </div>
      <div className="space-y-2">
        {HR_ZONES.map(z => {
          const s = active.hr_zones_s[z.key] ?? 0;
          const pct = (s / total) * 100;
          const isCurrent = currentZone?.key === z.key;
          const isTarget = z.key === DEFAULT_TARGET_ZONE;
          return (
            <div key={z.key} className="flex items-center gap-3">
              <div className={`w-20 text-xs ${z.textClass} flex items-center gap-1`}>
                {z.label}
                {isCurrent && <span className="text-[8px] uppercase opacity-70">now</span>}
              </div>
              <div className={`flex-1 h-2.5 rounded-full bg-neutral-800 overflow-hidden border ${isTarget ? z.borderClass : "border-transparent"}`}>
                <div className={`h-full ${z.bgClass} transition-all duration-700`} style={{ width: `${pct}%` }} />
              </div>
              <div className="w-12 text-right text-xs text-neutral-400 tabular-nums">
                {fmtClock(s)}
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}

interface ChartPoint {
  t: number;
  hr: number | null;
  speed: number | null;
}

function buildChartData(samples: TreadmillSample[], startedAt: string): ChartPoint[] {
  const start = new Date(startedAt).getTime();
  return samples
    .filter(s => new Date(s.ts).getTime() >= start)
    .map(s => ({
      t: Math.round((new Date(s.ts).getTime() - start) / 1000),
      hr: s.hr_bpm && s.hr_bpm > 0 ? s.hr_bpm : null,
      speed: s.speed_mph ?? null,
    }));
}

function tickFormatter(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const r = seconds % 60;
  return m > 0 ? `${m}:${String(r).padStart(2, "0")}` : `${r}s`;
}

function HrSpeedChart({ data }: { data: ChartPoint[] }) {
  if (data.length < 2) {
    return (
      <div className="text-xs text-neutral-500 italic">
        gathering samples… ({data.length})
      </div>
    );
  }
  return (
    <div className="h-56 sm:h-64 w-full">
      <ResponsiveContainer>
        <LineChart data={data} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#262626" />
          <XAxis
            dataKey="t"
            type="number"
            domain={["dataMin", "dataMax"]}
            tickFormatter={tickFormatter}
            stroke="#737373"
            fontSize={10}
          />
          <YAxis
            yAxisId="hr"
            domain={[60, 200]}
            stroke="#fb7185"
            fontSize={10}
            width={28}
          />
          <YAxis
            yAxisId="speed"
            orientation="right"
            domain={[0, 8]}
            stroke="#34d399"
            fontSize={10}
            width={28}
          />
          <Tooltip
            contentStyle={{
              background: "#171717", border: "1px solid #262626",
              fontSize: 12, borderRadius: 8,
            }}
            labelFormatter={(t) => `t+${tickFormatter(Number(t))}`}
            formatter={(v, k) => [v, k === "hr" ? "HR (bpm)" : "speed (mph)"]}
          />
          <Line
            yAxisId="hr" type="monotone" dataKey="hr"
            stroke="#fb7185" strokeWidth={2} dot={false}
            connectNulls isAnimationActive={false}
          />
          <Line
            yAxisId="speed" type="monotone" dataKey="speed"
            stroke="#34d399" strokeWidth={2} dot={false}
            connectNulls isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function cardiacDrift(data: ChartPoint[]): number | null {
  const points = data.filter(d => d.hr != null) as { t: number; hr: number }[];
  if (points.length < 30) return null;
  const n = points.length;
  const sumT = points.reduce((a, p) => a + p.t, 0);
  const sumH = points.reduce((a, p) => a + p.hr, 0);
  const sumTH = points.reduce((a, p) => a + p.t * p.hr, 0);
  const sumTT = points.reduce((a, p) => a + p.t * p.t, 0);
  const denom = n * sumTT - sumT * sumT;
  if (denom === 0) return null;
  const slopePerSec = (n * sumTH - sumT * sumH) / denom;
  return slopePerSec * 60;
}

function ChartCard({ active }: { active: ActiveWorkout }) {
  const { data: samples } = useQuery({
    queryKey: ["workouts.treadmill.samples"],
    queryFn: () => api.treadmillSamples(120),
    refetchInterval: SAMPLES_POLL_MS,
  });
  const points = samples ? buildChartData(samples, active.started_at) : [];
  const drift = cardiacDrift(points);
  return (
    <section className="rounded-2xl bg-neutral-900 border border-neutral-800 p-4 sm:p-6 space-y-3">
      <div className="flex items-baseline justify-between">
        <div className="text-xs uppercase tracking-wide text-neutral-400">HR + speed</div>
        {drift != null && (
          <div className="text-[10px] text-neutral-500" title="Cardiac drift — lower is fitter; ~5 bpm/30min indicates strong aerobic fitness">
            drift {drift >= 0 ? "+" : ""}{drift.toFixed(2)} bpm/min
          </div>
        )}
      </div>
      <HrSpeedChart data={points} />
    </section>
  );
}

function CoachingHint({ active }: { active: ActiveWorkout }) {
  const speed = active.current_speed_mph ?? active.avg_speed_mph;
  const hr = active.current_hr ?? active.avg_hr;
  const advice = zoneAdvice(hr, speed);
  if (!advice) return null;
  return (
    <section className="rounded-xl bg-neutral-900 border border-neutral-800 px-4 py-3 text-sm text-neutral-300">
      <div className="text-[10px] uppercase tracking-wide text-neutral-500 mb-1">coach</div>
      {advice}
    </section>
  );
}

function StatsGrid({ active }: { active: ActiveWorkout }) {
  const elapsedHr = Math.max(1 / 60, elapsedSeconds(active.started_at) / 3600);
  const kcalPerHr = Math.round(active.calories / elapsedHr);
  return (
    <section className="rounded-2xl bg-neutral-900 border border-neutral-800 p-4 sm:p-6">
      <div className="text-xs uppercase tracking-wide text-neutral-400 mb-3">Session stats</div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-3 text-sm">
        <Stat label="avg HR" value={active.avg_hr ? `${active.avg_hr} bpm` : "—"} />
        <Stat label="max HR" value={active.max_hr ? `${active.max_hr} bpm` : "—"} />
        <Stat label="avg speed" value={`${active.avg_speed_mph.toFixed(1)} mph`} />
        <Stat label="max speed" value={`${active.max_speed_mph.toFixed(1)} mph`} />
        <Stat label="avg grade" value={`${active.avg_grade_pct.toFixed(1)}%`} />
        <Stat label="max grade" value={`${active.max_grade_pct.toFixed(1)}%`} />
        <Stat label="calories" value={String(active.calories)} />
        <Stat label="burn rate" value={`${kcalPerHr} kcal/hr`} />
      </div>
    </section>
  );
}

/** Live treadmill cards. Pure presentational — the host page supplies the
 *  ActiveWorkout and handles the outer layout / header. */
export function ActiveTreadmillView({ active }: { active: ActiveWorkout }) {
  return (
    <>
      <HeroGauges active={active} />
      <CoachingHint active={active} />
      <ZoneBars active={active} />
      <ChartCard active={active} />
      <StatsGrid active={active} />
    </>
  );
}
