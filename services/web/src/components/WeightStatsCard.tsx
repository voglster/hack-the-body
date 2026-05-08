/**
 * Weight numbers above the chart.
 *
 * Two numbers describe "rate":
 *   - smoothed Δ (lead with this)  — (today's 7d avg) − (7d avg N days ago).
 *     Stable; what people mean by "am I losing".
 *   - regression trend (secondary) — least-squares slope through every
 *     intraday weigh-in. Reacts faster but inflates when the window
 *     happens to start on a high reading.
 *
 * The "since 4/26" footer always reflects actual elapsed days, not a
 * 28d label that lies during early protocol.
 */
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { kgToLbs } from "../lib/format";
import { PROTOCOL_START_ISO, sinceProtocolStart } from "../lib/protocol";
import {
  ratePerWeek,
  rollingAverage,
  smoothedRatePerWeek,
  type Point,
} from "../lib/trend";
import type { UserTargets } from "../api/types";

interface RateClass {
  label: string;
  tone: "good" | "warn" | "info" | "bad" | "neutral";
}

function classifyRate(
  ratePerWeekLb: number | null,
  targets: UserTargets | undefined,
): RateClass {
  if (ratePerWeekLb == null) return { label: "—", tone: "neutral" };
  const lo = targets?.weekly_loss_rate_min_lb ?? null;
  const hi = targets?.weekly_loss_rate_max_lb ?? null;
  const loss = -ratePerWeekLb;
  if (lo == null || hi == null) {
    if (loss > 0.1) return { label: "losing", tone: "good" };
    if (loss < -0.1) return { label: "gaining", tone: "bad" };
    return { label: "flat", tone: "info" };
  }
  const tol = 0.25;
  if (loss >= lo - tol && loss <= hi + tol) return { label: "on target", tone: "good" };
  if (loss > hi + tol) return { label: "too fast", tone: "warn" };
  if (loss > 0) return { label: "too slow", tone: "warn" };
  if (loss > -0.25) return { label: "stalled", tone: "warn" };
  return { label: "gaining", tone: "bad" };
}

const TONE_CLASS: Record<RateClass["tone"], string> = {
  good: "text-emerald-300 bg-emerald-900/30 border-emerald-800/50",
  warn: "text-amber-300 bg-amber-900/30 border-amber-800/50",
  info: "text-sky-300 bg-sky-900/30 border-sky-800/50",
  bad: "text-red-300 bg-red-900/30 border-red-800/50",
  neutral: "text-neutral-400 bg-neutral-800/40 border-neutral-700/50",
};

function formatRate(lbPerWeek: number | null): string {
  if (lbPerWeek == null) return "—";
  const sign = lbPerWeek > 0 ? "+" : "";
  return `${sign}${lbPerWeek.toFixed(2)} lb/wk`;
}

function formatLb(lb: number): string {
  const sign = lb > 0 ? "+" : lb < 0 ? "−" : "";
  return `${sign}${Math.abs(lb).toFixed(1)} lb`;
}

function etaWeeks(currentLb: number, goalLb: number, ratePerWeekLb: number | null): string {
  if (ratePerWeekLb == null) return "—";
  const distance = currentLb - goalLb;
  if (distance <= 0) return "at goal";
  const lossRate = -ratePerWeekLb;
  if (lossRate <= 0.05) return "—";
  const weeks = distance / lossRate;
  if (weeks < 1) return "<1 wk";
  if (weeks > 104) return ">2 yr";
  if (weeks > 8) return `${(weeks / 4.33).toFixed(1)} mo`;
  return `${weeks.toFixed(1)} wk`;
}

function formatProtocolStart(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

export function WeightStatsCard() {
  const { data: weightData } = useQuery({
    queryKey: ["weightRange", 60],
    queryFn: () => api.weightRange(60),
  });
  const { data: targets } = useQuery({
    queryKey: ["profile.targets"],
    queryFn: api.getTargets,
  });

  if (!weightData?.length) return null;

  const filtered = sinceProtocolStart(weightData);
  if (!filtered.length) return null;
  const pts: Point[] = filtered.map(d => ({ ts: d.ts, value: kgToLbs(d.kg) }));
  const latest = pts[pts.length - 1];
  const smoothed = rollingAverage(pts, 7);
  const latestSmoothed = smoothed[smoothed.length - 1];
  const firstSmoothed = smoothed[0];

  const smoothed7 = smoothedRatePerWeek(pts, 7);
  const rate7Trend = ratePerWeek(pts, 7);

  // Total elapsed days since first reading post-protocol.
  const elapsedMs =
    new Date(latest.ts).getTime() - new Date(firstSmoothed.ts).getTime();
  const elapsedDays = elapsedMs / 86_400_000;
  const sinceStartLb = latestSmoothed.avg - firstSmoothed.avg;
  const sinceStartRate = elapsedDays > 0
    ? (sinceStartLb / elapsedDays) * 7
    : null;

  const goal = targets?.goal_weight_lb ?? null;
  const toGoal = goal != null ? latestSmoothed.avg - goal : null;
  const cls = classifyRate(smoothed7.rate ?? sinceStartRate, targets);

  const isEarlyProtocol = elapsedDays < 14;

  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-4 space-y-3">
      <div className="flex items-baseline justify-between gap-2">
        <div className="text-xs uppercase tracking-wide text-neutral-400">Weight</div>
        <div className={`text-[11px] px-2 py-0.5 rounded border ${TONE_CLASS[cls.tone]}`}>
          {cls.label}
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="latest" value={`${latest.value.toFixed(1)} lb`} />
        <Stat label="7d avg" value={`${latestSmoothed.avg.toFixed(1)} lb`} />
        <Stat
          label="last 7d"
          value={formatRate(smoothed7.rate)}
          hint="7d avg now vs 7d ago"
        />
        <Stat
          label="trend pace"
          value={formatRate(rate7Trend)}
          hint="regression — reacts to single weigh-ins"
        />
      </div>
      <div className="text-[11px] text-neutral-400 pt-1 border-t border-neutral-800
                      flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span>
          since {formatProtocolStart(PROTOCOL_START_ISO)}
          <span className="text-neutral-500"> ({elapsedDays.toFixed(0)}d)</span>:
          {" "}
          <span className="text-neutral-200 tabular-nums">
            {formatLb(sinceStartLb)}
          </span>
          {sinceStartRate != null && (
            <span className="text-neutral-500"> · {formatRate(sinceStartRate)}</span>
          )}
        </span>
      </div>
      {isEarlyProtocol && (
        <div className="text-[11px] text-amber-300/80 bg-amber-900/15 border
                        border-amber-800/40 rounded px-2 py-1.5 leading-snug">
          Early protocol — first 1–2 weeks include water + glycogen drop
          (~2–4 lb that isn&apos;t fat). Real sustainable rate emerges around
          day 14.
        </div>
      )}
      {goal != null && toGoal != null && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 pt-1 border-t border-neutral-800">
          <Stat label="goal" value={`${goal.toFixed(0)} lb`} />
          <Stat
            label="to goal"
            value={toGoal > 0 ? `−${toGoal.toFixed(1)} lb` : "at goal"}
          />
          <Stat
            label="ETA"
            value={etaWeeks(latestSmoothed.avg, goal, smoothed7.rate ?? sinceStartRate)}
          />
          {targets?.weekly_loss_rate_min_lb != null
              && targets.weekly_loss_rate_max_lb != null && (
            <Stat
              label="target band"
              value={`${targets.weekly_loss_rate_min_lb}–${targets.weekly_loss_rate_max_lb} lb/wk`}
            />
          )}
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div title={hint}>
      <div className="text-[11px] uppercase tracking-wide text-neutral-500">{label}</div>
      <div className="text-base tabular-nums">{value}</div>
    </div>
  );
}
