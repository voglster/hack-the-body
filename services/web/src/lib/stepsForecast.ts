/** Shared step-forecast math used by both the dashboard StepsTodayCard
 *  and the kiosk hero. Source of truth lives here. */

export const ACTIVITY_CURVE: [number, number][] = [
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

export function expectedFractionAt(now: Date): number {
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

export interface Forecast {
  fractionDone: number;        // 0..1+ of goal
  expectedFraction: number;    // 0..1 of goal we should have hit by now
  projected: number;           // projected end-of-day steps
  status: "early" | "ahead" | "on-pace" | "behind" | "no-goal" | "miss";
  // Plain-english one-liner.
  message: string;
  needPerHour: number | null;  // steps/hr needed from now to make goal
}

export function forecast(steps: number, goal: number | null, now: Date): Forecast {
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
