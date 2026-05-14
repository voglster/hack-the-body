import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";
import { forecast } from "../../lib/stepsForecast";
import { localDayBoundsUTC, todayLocalISO } from "../../lib/tz";

export function KioskStepsHero() {
  const summaryQ = useQuery({
    queryKey: ["summary"],
    queryFn: api.summary,
    refetchInterval: 5 * 60_000,
  });
  const stepsQ = useQuery({
    queryKey: ["steps-today"],
    queryFn: () => {
      const { start, end } = localDayBoundsUTC(todayLocalISO());
      return api.stepsDay(start, end);
    },
    refetchInterval: 60_000,
  });

  const steps = stepsQ.data?.total ?? 0;
  const goal = summaryQ.data?.daily_summary?.step_goal ?? null;
  const f = forecast(steps, goal, new Date());
  const pct = Math.min(100, Math.round(f.fractionDone * 100));
  const expectedPct = Math.min(100, Math.round(f.expectedFraction * 100));

  return (
    <section className="rounded-2xl border border-neutral-800 bg-neutral-950 p-8 flex flex-col gap-4">
      <div className="text-xs uppercase tracking-widest text-neutral-500">
        Steps
      </div>
      <div className="flex items-baseline gap-3">
        <div className="text-6xl font-semibold tabular-nums">
          {steps.toLocaleString()}
        </div>
        {goal != null && (
          <div className="text-2xl text-neutral-500 tabular-nums">
            / {goal.toLocaleString()}
          </div>
        )}
      </div>
      <div className="relative h-3 bg-neutral-800 rounded-full overflow-hidden">
        <div
          className="absolute top-0 left-0 h-full bg-emerald-500"
          style={{ width: `${pct}%` }}
        />
        <div
          className="absolute top-0 h-full w-[2px] bg-neutral-400"
          style={{ left: `${expectedPct}%` }}
          aria-label="expected by now"
        />
      </div>
      <div className="text-lg text-neutral-400">{f.message}</div>
    </section>
  );
}
