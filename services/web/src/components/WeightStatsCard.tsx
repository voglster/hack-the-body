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
  rollingAverage,
  smoothedRatePerWeek,
  type Point,
} from "../lib/trend";
import type { UserTargets, WeightProjection } from "../api/types";

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

/** Linear-extrapolation ETA — kept as a secondary stat next to the
 *  decay-based projection so we can sanity-check one against the other. */
function etaWeeksLinear(currentLb: number, goalLb: number, ratePerWeekLb: number | null): string {
  if (ratePerWeekLb == null) return "—";
  const distance = currentLb - goalLb;
  if (distance <= 0) return "at goal";
  const lossRate = -ratePerWeekLb;
  if (lossRate <= 0.05) return "—";
  const weeks = distance / lossRate;
  if (weeks > 104) return ">2 yr";
  // Lead with the concrete date — a target you can circle on a
  // calendar is more motivating than "2.7 mo". Keep the duration in
  // parens as a sanity check.
  const target = new Date(Date.now() + weeks * 7 * 86_400_000);
  const dateStr = target.toLocaleDateString(undefined, {
    month: "short", day: "numeric", year: "numeric",
  });
  let span: string;
  if (weeks < 1) span = "<1 wk";
  else if (weeks > 8) span = `${(weeks / 4.33).toFixed(1)} mo`;
  else span = `${weeks.toFixed(1)} wk`;
  return `${dateStr} (${span})`;
}

/** Format the decay-projection ETA the API returned, or null if the API
 *  has no fit / says the goal is unreachable. The caller falls back to
 *  the linear ETA when this is null. */
function formatProjectionEta(p: WeightProjection | undefined): string | null {
  if (!p) return null;
  if (p.reason === "asymptote_above_goal" && p.fit) {
    return `plateau ~${p.fit.asymptote_lb.toFixed(0)} lb`;
  }
  if (!p.eta) return null;
  const target = new Date(p.eta.date);
  const dateStr = target.toLocaleDateString(undefined, {
    month: "short", day: "numeric", year: "numeric",
  });
  const weeks = (target.getTime() - Date.now()) / (7 * 86_400_000);
  const span = weeks > 8 ? `${(weeks / 4.33).toFixed(1)} mo` : `${weeks.toFixed(1)} wk`;
  return `${dateStr} (${span})`;
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
  // Server-side exponential-decay projection — front-end stays dumb,
  // just renders whatever the API returns. Refetch is independent of
  // weightRange so changes to the underlying data update both.
  const { data: projection } = useQuery({
    queryKey: ["weightProjection", targets?.goal_weight_lb],
    queryFn: () => api.weightProjection(targets?.goal_weight_lb ?? undefined),
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
          label="plateau"
          value={projection?.fit ? `${projection.fit.asymptote_lb.toFixed(0)} lb` : "—"}
          hint={
            projection?.fit
              ? `where you'd settle at current effort — decay fit, R²=${projection.fit.r_squared.toFixed(2)}`
              : "needs ≥21d of data"
          }
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
            value={formatProjectionEta(projection)
              ?? etaWeeksLinear(latestSmoothed.avg, goal, smoothed7.rate ?? sinceStartRate)}
            hint={projection?.fit
              ? `decay fit R²=${projection.fit.r_squared.toFixed(2)}, n=${projection.fit.n_points}`
              : "linear extrapolation (decay fit needs ≥21d of data)"}
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
