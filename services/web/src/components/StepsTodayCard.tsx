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

const WAKE_HOUR = 6;
const SLEEP_HOUR = 24;

function wakingFractionElapsed(now: Date): number {
  const hour = now.getHours() + now.getMinutes() / 60;
  return Math.max(0, Math.min(1, (hour - WAKE_HOUR) / (SLEEP_HOUR - WAKE_HOUR)));
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
  const expectedFraction = wakingFractionElapsed(now);
  const projected = expectedFraction > 0.02
    ? Math.round(steps / expectedFraction)
    : steps;

  // Hours of waking window left (until midnight).
  const hoursLeft = Math.max(0, SLEEP_HOUR - (now.getHours() + now.getMinutes() / 60));
  const remaining = Math.max(0, goal - steps);
  const needPerHour = hoursLeft > 0 && remaining > 0
    ? Math.round(remaining / hoursLeft)
    : null;

  if (expectedFraction < 0.05) {
    return {
      fractionDone, expectedFraction, projected, needPerHour,
      status: "early", message: "early — pace will calibrate after 7am",
    };
  }
  if (steps >= goal) {
    return {
      fractionDone, expectedFraction, projected, needPerHour: 0,
      status: "ahead", message: `goal hit — projected ${projected.toLocaleString()}`,
    };
  }
  // Are we on pace? Within 5% of expected = on-pace.
  const delta = fractionDone - expectedFraction;
  if (delta >= -0.05 && projected >= goal * 0.95) {
    return {
      fractionDone, expectedFraction, projected, needPerHour,
      status: "on-pace",
      message: `on pace — projected ${projected.toLocaleString()}`,
    };
  }
  if (hoursLeft < 0.5 || projected < goal * 0.6) {
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
