/**
 * Live treadmill workout tile.
 *
 * Polls /workouts/active every 2s. Renders nothing when no workout is
 * active — appearing/disappearing automatically based on whether the
 * user is on the deck. Big speed and HR readouts; secondary line for
 * distance / time / grade / calories.
 */
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import type { ActiveWorkout } from "../api/types";

const POLL_MS = 2000;

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

function hrZoneColor(hr: number | null): string {
  if (hr == null || hr <= 0) return "text-neutral-400";
  if (hr < 110) return "text-sky-400";
  if (hr < 130) return "text-emerald-400";
  if (hr < 150) return "text-amber-400";
  if (hr < 170) return "text-orange-400";
  return "text-red-400";
}

function hrBarColor(hr: number | null): string {
  if (hr == null || hr <= 0) return "bg-neutral-600";
  if (hr < 110) return "bg-sky-500";
  if (hr < 130) return "bg-emerald-500";
  if (hr < 150) return "bg-amber-500";
  if (hr < 170) return "bg-orange-500";
  return "bg-red-500";
}

function speedBarPct(mph: number): number {
  // 0–8 mph maps to 0–100% — covers brisk run on most home decks.
  return Math.min(100, (mph / 8) * 100);
}

function hrBarPct(hr: number | null): number {
  if (hr == null || hr <= 0) return 0;
  // 50–190 bpm maps to 0–100%.
  return Math.min(100, Math.max(0, ((hr - 50) / 140) * 100));
}

function StatRow({ active }: { active: ActiveWorkout }) {
  return (
    <div className="grid grid-cols-4 gap-2 text-center">
      <Stat label="dist" value={`${active.distance_mi.toFixed(2)} mi`} />
      <Stat label="time" value={fmtClock(elapsedSeconds(active.started_at))} />
      <Stat label="grade" value={`${active.max_grade_pct.toFixed(1)}%`} sub="peak" />
      <Stat label="cal"  value={String(active.calories)} />
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-neutral-500">{label}</div>
      <div className="text-base sm:text-lg font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-[10px] text-neutral-600">{sub}</div>}
    </div>
  );
}

function GaugeRow({
  primary, primarySub, primaryColor, barPct, barColor,
}: {
  primary: string;
  primarySub: string;
  primaryColor: string;
  barPct: number;
  barColor: string;
}) {
  return (
    <div className="flex items-end gap-3">
      <div className="flex-1">
        <div className={`text-4xl sm:text-5xl font-bold tabular-nums leading-none ${primaryColor}`}>
          {primary}
        </div>
        <div className="text-xs text-neutral-500 mt-1">{primarySub}</div>
        <div className="mt-2 h-1.5 w-full rounded-full bg-neutral-800 overflow-hidden">
          <div className={`h-full ${barColor} transition-all duration-500`} style={{ width: `${barPct}%` }} />
        </div>
      </div>
    </div>
  );
}

export function ActiveWorkoutCard() {
  const { data: active } = useQuery({
    queryKey: ["workouts.active"],
    queryFn: api.activeWorkout,
    refetchInterval: POLL_MS,
    // Don't show stale data from the previous session: when the API
    // returns null the card should disappear immediately.
    staleTime: 0,
    gcTime: 0,
  });

  if (!active || active.status !== "active") return null;

  const speed = active.avg_speed_mph;  // The aggregator's average IS the rolling mean over the session
  // For a more "live" feel, use the latest sample's speed via /workouts/treadmill/samples?minutes=1
  // — left for a follow-up; the average converges fast at 2 Hz.
  const hr = active.avg_hr;

  return (
    <section className="rounded-2xl bg-gradient-to-br from-neutral-900 to-neutral-950 border border-emerald-700/40 p-4 sm:p-6 space-y-4 shadow-lg shadow-emerald-900/10">
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

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <GaugeRow
          primary={speed.toFixed(1)}
          primarySub={`mph · max ${active.max_speed_mph.toFixed(1)}`}
          primaryColor="text-emerald-300"
          barPct={speedBarPct(speed)}
          barColor="bg-emerald-500"
        />
        <GaugeRow
          primary={hr != null && hr > 0 ? String(hr) : "—"}
          primarySub={hr != null && hr > 0
            ? `bpm · max ${active.max_hr ?? "—"}`
            : "no strap detected"}
          primaryColor={hrZoneColor(hr)}
          barPct={hrBarPct(hr)}
          barColor={hrBarColor(hr)}
        />
      </div>

      <StatRow active={active} />
    </section>
  );
}
