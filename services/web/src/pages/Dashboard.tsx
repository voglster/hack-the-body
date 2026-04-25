import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import { HrvChart } from "../components/HrvChart";
import { MetricCard } from "../components/MetricCard";
import { SleepChart } from "../components/SleepChart";
import { StepsChart } from "../components/StepsChart";
import { WeightChart } from "../components/WeightChart";
import { WorkoutList } from "../components/WorkoutList";
import { formatDuration, formatLbs } from "../lib/format";

export function Dashboard() {
  const { data: summary } = useQuery({
    queryKey: ["summary"],
    queryFn: api.summary,
    refetchInterval: 60_000,
  });

  const qc = useQueryClient();
  const sync = useMutation({
    mutationFn: () => api.triggerIngest("garmin"),
    onSuccess: () => qc.invalidateQueries(),
  });

  return (
    <div className="max-w-6xl mx-auto px-4 py-8 space-y-8">
      <header className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">Hack the Body</h1>
        <button
          onClick={() => sync.mutate()}
          disabled={sync.isPending}
          className="text-xs px-3 py-1.5 rounded bg-neutral-800 hover:bg-neutral-700 disabled:opacity-50"
        >
          {sync.isPending ? "syncing..." : "sync garmin"}
        </button>
      </header>

      <section className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <MetricCard
          label="Weight"
          value={summary?.weight ? formatLbs(summary.weight.kg) : "—"}
          sub={summary?.weight ? summary.weight.ts.slice(0, 10) : undefined}
        />
        <MetricCard
          label="Sleep"
          value={summary?.sleep ? formatDuration(summary.sleep.duration_s) : "—"}
          sub={summary?.sleep?.score != null ? `score ${summary.sleep.score}` : undefined}
        />
        <MetricCard
          label="HRV"
          value={summary?.hrv ? `${summary.hrv.rmssd_ms.toFixed(0)} ms` : "—"}
        />
        <MetricCard
          label="VO2 Max"
          value={summary?.vo2max ? summary.vo2max.value.toFixed(1) : "—"}
        />
        <MetricCard
          label="Steps"
          value={summary?.daily_summary ? summary.daily_summary.steps.toLocaleString() : "—"}
          sub={
            summary?.daily_summary?.step_goal
              ? `goal ${summary.daily_summary.step_goal.toLocaleString()}`
              : undefined
          }
        />
      </section>

      <section>
        <h2 className="text-sm uppercase tracking-wide text-neutral-400 mb-2">Weight (60d, 7d avg)</h2>
        <WeightChart />
      </section>

      <section>
        <h2 className="text-sm uppercase tracking-wide text-neutral-400 mb-2">Steps (30d)</h2>
        <StepsChart />
      </section>

      <section>
        <h2 className="text-sm uppercase tracking-wide text-neutral-400 mb-2">Sleep (30d)</h2>
        <SleepChart />
      </section>

      <section>
        <h2 className="text-sm uppercase tracking-wide text-neutral-400 mb-2">HRV (30d)</h2>
        <HrvChart />
      </section>

      <section>
        <h2 className="text-sm uppercase tracking-wide text-neutral-400 mb-2">Recent workouts</h2>
        <WorkoutList />
      </section>
    </div>
  );
}
