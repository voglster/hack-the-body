import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { Summary } from "../api/types";
import { HrvChart } from "../components/HrvChart";
import { MetricCard } from "../components/MetricCard";
import { SleepChart } from "../components/SleepChart";
import { StepsChart } from "../components/StepsChart";
import { StepsTodayChart } from "../components/StepsTodayChart";
import { TodayMeals } from "../components/TodayMeals";
import { WeightChart } from "../components/WeightChart";
import { WorkoutList } from "../components/WorkoutList";
import { formatDuration, formatLbs } from "../lib/format";

interface CardData { label: string; value: string; sub?: string }

const weightCard = (s: Summary | undefined): CardData => ({
  label: "Weight",
  value: s?.weight ? formatLbs(s.weight.kg) : "—",
  sub: s?.weight?.ts.slice(0, 10),
});

const sleepCard = (s: Summary | undefined): CardData => ({
  label: "Sleep",
  value: s?.sleep ? formatDuration(s.sleep.duration_s) : "—",
  sub: s?.sleep?.score != null ? `score ${s.sleep.score}` : undefined,
});

const hrvCard = (s: Summary | undefined): CardData => ({
  label: "HRV",
  value: s?.hrv ? `${s.hrv.rmssd_ms.toFixed(0)} ms` : "—",
});

const vo2Card = (s: Summary | undefined): CardData => ({
  label: "VO2 Max",
  value: s?.vo2max ? s.vo2max.value.toFixed(1) : "—",
});

const stepsCard = (s: Summary | undefined, todaySteps: number | undefined): CardData => {
  const ds = s?.daily_summary;
  // Prefer live intraday total when available (updates every sync); fall back
  // to the daily-summary record (only refreshed by Garmin once per day).
  const value = todaySteps ?? ds?.steps;
  return {
    label: "Steps",
    value: value != null ? value.toLocaleString() : "—",
    sub: ds?.step_goal ? `goal ${ds.step_goal.toLocaleString()}` : undefined,
  };
};

function summaryToCards(s: Summary | undefined, todaySteps: number | undefined): CardData[] {
  return [weightCard(s), sleepCard(s), hrvCard(s), vo2Card(s), stepsCard(s, todaySteps)];
}

function SummaryCards({ summary, todaySteps }: {
  summary: Summary | undefined;
  todaySteps: number | undefined;
}) {
  return (
    <section className="grid grid-cols-2 md:grid-cols-5 gap-3">
      {summaryToCards(summary, todaySteps).map(c => (
        <MetricCard key={c.label} label={c.label} value={c.value} sub={c.sub} />
      ))}
    </section>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="text-sm uppercase tracking-wide text-neutral-400 mb-2">{title}</h2>
      {children}
    </section>
  );
}

function SyncButton() {
  const qc = useQueryClient();
  const sync = useMutation({
    mutationFn: () => api.triggerIngest("garmin"),
    onSuccess: () => qc.invalidateQueries(),
  });
  return (
    <button
      onClick={() => sync.mutate()}
      disabled={sync.isPending}
      className="text-xs px-3 py-1.5 rounded bg-neutral-800 hover:bg-neutral-700 disabled:opacity-50"
    >
      {sync.isPending ? "syncing..." : "sync garmin"}
    </button>
  );
}

export function Dashboard() {
  const { data: summary } = useQuery({
    queryKey: ["summary"],
    queryFn: api.summary,
    refetchInterval: 60_000,
  });
  const { data: stepsToday } = useQuery({
    queryKey: ["stepsToday"],
    queryFn: api.stepsToday,
    refetchInterval: 60_000,
  });

  return (
    <div className="max-w-6xl mx-auto px-4 py-8 space-y-8">
      <header className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold">Hack the Body</h1>
        <SyncButton />
      </header>

      <SummaryCards summary={summary} todaySteps={stepsToday?.total} />

      <Section title="Today’s food"><TodayMeals /></Section>
      <Section title="Today’s steps (15min buckets)"><StepsTodayChart /></Section>
      <Section title="Weight (60d, 7d avg)"><WeightChart /></Section>
      <Section title="Steps (30d)"><StepsChart /></Section>
      <Section title="Sleep (30d)"><SleepChart /></Section>
      <Section title="HRV (30d)"><HrvChart /></Section>
      <Section title="Recent workouts"><WorkoutList /></Section>
    </div>
  );
}
