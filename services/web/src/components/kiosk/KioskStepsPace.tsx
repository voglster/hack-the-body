import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from "recharts";

import { api } from "../../api/client";
import { useStepGoal } from "../../hooks/useStepGoal";
import { cumulative, hourOf, verdict, WAKE_HOUR } from "../../lib/stepsPace";
import { localDayBoundsUTC, todayLocalISO } from "../../lib/tz";

const STALE_HOURS = 1.5;
const INK = { pace: "#737373", grid: "#262626", axis: "#a3a3a3" };
const STATUS_INK = { ahead: "#34d399", "on-pace": "#34d399", done: "#34d399", behind: "#fbbf24" };

function clock(hour: number): string {
  const h = Math.floor(hour);
  const m = Math.round((hour - h) * 60);
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}${m ? `:${String(m).padStart(2, "0")}` : ""}${h >= 12 ? "pm" : "am"}`;
}

function bedHourFrom(lightsOut: string | null | undefined): number {
  const [h, m] = (lightsOut ?? "22:00").split(":").map(Number);
  return h + m / 60;
}

/**
 * "It's 2:30 — am I on track for 12k?" Steps so far against an even pace from
 * 7am to lights-out. Judged at the last synced minute, so an unsynced watch
 * reads as stale rather than as sitting still.
 */
export function KioskStepsPace() {
  const summary = useQuery({ queryKey: ["summary"], queryFn: api.summary, refetchInterval: 5 * 60_000 });
  const targets = useQuery({ queryKey: ["profile.targets"], queryFn: api.getTargets });
  const goal = useStepGoal(summary.data);
  const { start, end } = localDayBoundsUTC(todayLocalISO());
  const steps = useQuery({
    queryKey: ["steps-day", start],
    queryFn: () => api.stepsDay(start, end),
    refetchInterval: 5 * 60_000,
  });
  if (!goal || !steps.data) return null;

  const bed = bedHourFrom(targets.data?.lights_out_local);
  const actual = [{ hour: WAKE_HOUR, steps: 0 }, ...cumulative(steps.data.buckets)
    .filter((p) => p.hour >= WAKE_HOUR)];
  const last = actual[actual.length - 1];
  const now = hourOf(new Date());
  const stale = now - last.hour > STALE_HOURS;
  const v = verdict(steps.data.total, last.hour, now, goal, bed);
  const ink = STATUS_INK[v.status];
  const pace = [{ hour: WAKE_HOUR, steps: 0 }, { hour: bed, steps: goal }];

  return (
    <section className="flex flex-col gap-3">
      <p className="text-3xl">
        <span style={{ color: ink }}>{v.headline}</span>
        <span className="text-neutral-400">
          {" · "}{steps.data.total.toLocaleString()} of {goal.toLocaleString()} steps
          {v.status !== "done" && v.needPerHour != null && ` · ${v.needPerHour.toLocaleString()}/hr to finish`}
        </span>
      </p>
      {stale && (
        <p className="text-2xl text-amber-400">
          Watch last synced {clock(last.hour)}. Open Garmin Connect.
        </p>
      )}
      <div className="h-64" role="img"
           aria-label={`Steps ${steps.data.total} against an even pace to ${goal} by ${clock(bed)}: ${v.headline}`}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid stroke={INK.grid} vertical={false} />
            <XAxis type="number" dataKey="hour" domain={[WAKE_HOUR, Math.ceil(bed)]} ticks={[7, 10, 13, 16, 19, 22]}
                   tickFormatter={clock} stroke={INK.axis} tick={{ fontSize: 18 }} tickLine={false} />
            <YAxis type="number" domain={[0, Math.max(goal, steps.data.total)]} ticks={[0, goal / 2, goal]}
                   tickFormatter={(n: number) => `${Math.round(n / 1000)}k`} stroke={INK.axis}
                   tick={{ fontSize: 18 }} tickLine={false} axisLine={false} width={48} />
            <Line data={pace} dataKey="steps" stroke={INK.pace} strokeWidth={2} strokeDasharray="6 6"
                  dot={false} isAnimationActive={false} />
            <Line data={actual} dataKey="steps" stroke={ink} strokeWidth={4} dot={false}
                  isAnimationActive={false} />
            <ReferenceLine x={now} stroke={INK.axis} strokeDasharray="2 4" />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xl text-neutral-500">Dashed: even pace to {goal.toLocaleString()} by {clock(bed)}</p>
    </section>
  );
}
