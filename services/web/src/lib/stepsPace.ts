import type { StepsBucket } from "../api/types";

/** The even-pace line: goal spread evenly from waking to lights-out. */
export const WAKE_HOUR = 7;
export const ON_PACE_BAND = 0.05;

export interface PacePoint { hour: number; steps: number }

export function hourOf(d: Date): number {
  return d.getHours() + d.getMinutes() / 60;
}

export function paceAt(hour: number, goal: number, bedHour: number, wakeHour = WAKE_HOUR): number {
  if (hour <= wakeHour) return 0;
  if (hour >= bedHour) return goal;
  return Math.round(goal * (hour - wakeHour) / (bedHour - wakeHour));
}

/** Running total at the end of each bucket, local hours. */
export function cumulative(buckets: StepsBucket[]): PacePoint[] {
  let total = 0;
  return [...buckets]
    .sort((a, b) => a.end_ts.localeCompare(b.end_ts))
    .map((b) => {
      total += b.steps;
      return { hour: hourOf(new Date(b.end_ts)), steps: total };
    });
}

export interface PaceVerdict {
  status: "ahead" | "on-pace" | "behind" | "done";
  delta: number;            // steps vs the even-pace line at the data's last point
  needPerHour: number | null;
  headline: string;
}

export function verdict(steps: number, asOfHour: number, nowHour: number,
                        goal: number, bedHour: number): PaceVerdict {
  const fmt = (n: number) => Math.abs(n).toLocaleString();
  if (steps >= goal) {
    return { status: "done", delta: steps - paceAt(asOfHour, goal, bedHour), needPerHour: 0,
             headline: `${goal.toLocaleString()} done` };
  }
  const delta = steps - paceAt(asOfHour, goal, bedHour);
  const hoursLeft = bedHour - nowHour;
  const needPerHour = hoursLeft > 0 ? Math.round((goal - steps) / hoursLeft) : null;
  const band = goal * ON_PACE_BAND;
  if (delta >= band) return { status: "ahead", delta, needPerHour, headline: `Ahead by ${fmt(delta)}` };
  if (delta > -band) return { status: "on-pace", delta, needPerHour, headline: "On pace" };
  return { status: "behind", delta, needPerHour, headline: `Behind by ${fmt(delta)}` };
}
