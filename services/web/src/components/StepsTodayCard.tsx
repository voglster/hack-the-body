/**
 * Always-visible "Steps today" hero card.
 *
 * Big number (current count), goal context, progress bar with two markers
 * (where you are vs. where you should be by now), and a one-liner that
 * answers "am I going to hit my goal?". The pace math assumes a 6am→
 * midnight walking window — anything before 6am counts as on-pace by
 * default since most people aren't out walking yet.
 */
import type { Summary } from "../api/types";

/**
 * Typical cumulative-step curve over the day. Assumes a person who walks
 * a bit in the morning, more around lunch, and significantly more in the
 * evening (post-work walk + after-dinner). Each entry is [hour, fraction
 * of daily total cumulatively reached by that hour]. We linearly
 * interpolate between points at runtime.
 *
 * Calibrated rough numbers — not from this user's data yet. TODO once
 * we've collected a few weeks of intraday history we can fit a per-user
 * curve and replace this with that.
 */
const ACTIVITY_CURVE: [number, number][] = [
  [0, 0.00],
  [6, 0.02],
  [8, 0.07],
  [10, 0.15],
  [12, 0.25],
  [14, 0.38],
  [16, 0.52],
  [18, 0.70],
  [20, 0.88],
  [22, 0.97],
  [24, 1.00],
];

function expectedFractionAt(now: Date): number {
  const h = now.getHours() + now.getMinutes() / 60;
  for (let i = 0; i < ACTIVITY_CURVE.length - 1; i++) {
    const [h1, f1] = ACTIVITY_CURVE[i];
    const [h2, f2] = ACTIVITY_CURVE[i + 1];
    if (h >= h1 && h <= h2) {
      const t = (h - h1) / (h2 - h1);
      return f1 + t * (f2 - f1);
    }
  }
  return 1;
}

interface Forecast {
  fractionDone: number;        // 0..1+ of goal
  expectedFraction: number;    // 0..1 of goal we should have hit by now
  projected: number;           // projected end-of-day steps
  status: "early" | "ahead" | "on-pace" | "behind" | "no-goal" | "miss";
  // Plain-english one-liner.
  message: string;
  needPerHour: number | null;  // steps/hr needed from now to make goal
}

function forecast(steps: number, goal: number | null, now: Date): Forecast {
  if (!goal || goal <= 0) {
    return {
      fractionDone: 0, expectedFraction: 0, projected: steps,
      status: "no-goal", message: "no daily step goal set", needPerHour: null,
    };
  }
  const fractionDone = steps / goal;
  const expectedFraction = expectedFractionAt(now);
  const remainingFraction = Math.max(0.001, 1 - expectedFraction);
  const projected = expectedFraction > 0.02
    ? Math.round(steps / expectedFraction)
    : Math.round(steps + goal * remainingFraction);  // very early: assume average rest-of-day

  const hourNow = now.getHours() + now.getMinutes() / 60;
  // Active window ends at 11pm — that's where the curve plateaus in practice.
  const hoursLeft = Math.max(0, 23 - hourNow);
  const remaining = Math.max(0, goal - steps);
  const needPerHour = hoursLeft > 0 && remaining > 0
    ? Math.round(remaining / hoursLeft)
    : null;

  if (steps >= goal) {
    return {
      fractionDone, expectedFraction, projected, needPerHour: 0,
      status: "ahead", message: `goal hit — projected ${projected.toLocaleString()}`,
    };
  }
  if (hourNow < 7) {
    return {
      fractionDone, expectedFraction, projected, needPerHour,
      status: "early", message: "early — pace calibrates after 8am",
    };
  }

  // Decide on pace using projection vs goal, with a tighter band as the
  // day gets later (less time = less recovery room).
  const projectionPct = projected / goal;
  if (projectionPct >= 0.95) {
    return {
      fractionDone, expectedFraction, projected, needPerHour,
      status: "on-pace",
      message: `on pace — projected ${projected.toLocaleString()}`,
    };
  }
  // Only call it a "miss" when the runway is short. Before 8pm there's
  // still a typical evening-walk's worth of steps left to come.
  if (hourNow >= 21 && projectionPct < 0.85) {
    return {
      fractionDone, expectedFraction, projected, needPerHour,
      status: "miss",
      message: `${remaining.toLocaleString()} short — likely missing today`,
    };
  }
  return {
    fractionDone, expectedFraction, projected, needPerHour,
    status: "behind",
    message: needPerHour != null
      ? `${needPerHour.toLocaleString()}/hr needed to hit ${goal.toLocaleString()}`
      : `${remaining.toLocaleString()} to go`,
  };
}

const STATUS_TONE: Record<Forecast["status"], { bar: string; pill: string }> = {
  early:   { bar: "bg-neutral-500",  pill: "text-neutral-400" },
  ahead:   { bar: "bg-emerald-500",  pill: "text-emerald-300" },
  "on-pace":  { bar: "bg-emerald-500", pill: "text-emerald-300" },
  behind:  { bar: "bg-amber-500",    pill: "text-amber-300" },
  miss:    { bar: "bg-red-500",      pill: "text-red-300" },
  "no-goal": { bar: "bg-neutral-500", pill: "text-neutral-400" },
};

export function StepsTodayCard({ summary, todaySteps }: {
  summary: Summary | undefined;
  todaySteps: number | undefined;
}) {
  const ds = summary?.daily_summary;
  const steps = todaySteps ?? ds?.steps ?? 0;
  const goal = ds?.step_goal ?? null;
  const f = forecast(steps, goal, new Date());
  const tone = STATUS_TONE[f.status];

  // Position of the "expected pace" marker on the bar.
  const expectedPct = goal ? Math.min(100, f.expectedFraction * 100) : 0;
  const donePct = goal ? Math.min(100, f.fractionDone * 100) : 0;

  return (
    <section className="rounded-2xl bg-neutral-900 border border-neutral-800 p-4 sm:p-6 space-y-4">
      <div className="flex items-baseline justify-between gap-2">
        <div className="text-xs uppercase tracking-wide text-neutral-400">Steps today</div>
        {goal && (
          <div className="text-xs text-neutral-500 tabular-nums">
            {Math.round(f.fractionDone * 100)}% of {goal.toLocaleString()}
          </div>
        )}
      </div>

      <div className="flex items-end gap-3">
        <div className="text-5xl sm:text-6xl font-bold tabular-nums leading-none">
          {steps.toLocaleString()}
        </div>
        {goal && (
          <div className="pb-1 text-sm text-neutral-500 tabular-nums">
            / {goal.toLocaleString()}
          </div>
        )}
      </div>

      {goal && (
        <div className="relative h-2.5 w-full rounded-full bg-neutral-800 overflow-visible">
          <div
            className={`h-full rounded-full ${tone.bar}`}
            style={{ width: `${donePct}%` }}
          />
          {/* expected-pace marker (where you "should be" right now) */}
          {f.status !== "early" && (
            <div
              className="absolute top-[-3px] bottom-[-3px] w-0.5 bg-neutral-300"
              style={{ left: `${expectedPct}%` }}
              aria-label="expected pace"
              title="expected pace by now"
            />
          )}
        </div>
      )}

      <div className={`text-sm font-medium ${tone.pill}`}>{f.message}</div>
    </section>
  );
}
