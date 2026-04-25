import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { Summary } from "../api/types";
import { CoachCard } from "../components/CoachCard";
import { NotificationsCard } from "../components/NotificationsCard";
import { WaterCard } from "../components/WaterCard";
import { HrvChart } from "../components/HrvChart";
import { MetricCard } from "../components/MetricCard";
import { SleepChart } from "../components/SleepChart";
import { StepsChart } from "../components/StepsChart";
import { StepsTodayChart } from "../components/StepsTodayChart";
import { SyncStatusFooter } from "../components/SyncStatusFooter";
import { TodayMeals } from "../components/TodayMeals";
import { WeightChart } from "../components/WeightChart";
import { WorkoutList } from "../components/WorkoutList";
import { clearApiKey } from "../lib/auth";
import { formatDuration, formatLbs } from "../lib/format";
import { localDayBoundsUTC, todayLocalISO } from "../lib/tz";

interface CardData {
  label: string; value: string; sub?: string;
  progress?: number; behindPace?: boolean;
}

/** Fraction of waking hours that have elapsed (6am to midnight = 18hr).
 *  Returns 0..1, capped. Used to grade "are you on pace for the step goal?". */
function wakingFractionElapsed(): number {
  const now = new Date();
  const hour = now.getHours() + now.getMinutes() / 60;
  const start = 6;
  const end = 24;
  return Math.min(1, Math.max(0, (hour - start) / (end - start)));
}

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
  const steps = todaySteps ?? ds?.steps ?? 0;
  const goal = ds?.step_goal ?? null;
  if (goal && goal > 0) {
    const fraction = steps / goal;
    const expected = wakingFractionElapsed();
    const behindPace = fraction < expected - 0.05;
    return {
      label: "Steps",
      value: steps.toLocaleString(),
      sub: `${Math.round(fraction * 100)}% of ${goal.toLocaleString()}`,
      progress: fraction,
      behindPace,
    };
  }
  return {
    label: "Steps",
    value: steps != null ? steps.toLocaleString() : "—",
  };
};

function summaryToCards(s: Summary | undefined, todaySteps: number | undefined): CardData[] {
  return [stepsCard(s, todaySteps), sleepCard(s), weightCard(s), hrvCard(s), vo2Card(s)];
}

function SummaryCards({ summary, todaySteps }: {
  summary: Summary | undefined;
  todaySteps: number | undefined;
}) {
  return (
    // 2 cols on phone, 5 cols on desktop. Order matters on mobile —
    // steps + sleep are what you check most; weight/HRV/VO2 are secondary.
    <section className="grid grid-cols-2 md:grid-cols-5 gap-2 sm:gap-3">
      {summaryToCards(summary, todaySteps).map(c => (
        <MetricCard
          key={c.label}
          label={c.label}
          value={c.value}
          sub={c.sub}
          progress={c.progress}
          behindPace={c.behindPace}
        />
      ))}
    </section>
  );
}

function Section({ title, children, defaultOpen = true }: {
  title: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  // <details> is the cheapest "collapsible card" we can build: it's a single
  // native element with no JS, scrolls correctly, and preserves the open
  // state across re-renders.
  return (
    <details open={defaultOpen} className="group">
      <summary className="cursor-pointer list-none flex items-center justify-between text-sm uppercase tracking-wide text-neutral-400 mb-2 select-none">
        <span>{title}</span>
        <span className="text-neutral-600 group-open:rotate-90 transition-transform">▸</span>
      </summary>
      <div>{children}</div>
    </details>
  );
}

function HeaderActions() {
  const qc = useQueryClient();
  const sync = useMutation({
    mutationFn: () => api.triggerIngest("garmin"),
    onSuccess: () => qc.invalidateQueries(),
  });
  return (
    <div className="flex items-center gap-2">
      <button
        onClick={() => sync.mutate()}
        disabled={sync.isPending}
        className="text-xs px-3 py-2 rounded bg-neutral-800 hover:bg-neutral-700 active:bg-neutral-600 disabled:opacity-50 min-h-[44px] sm:min-h-0 sm:py-1.5"
        aria-label="trigger garmin sync"
      >
        {sync.isPending ? "..." : "↻"}
      </button>
      <button
        onClick={() => clearApiKey()}
        className="text-xs px-3 py-2 rounded bg-neutral-800 hover:bg-neutral-700 active:bg-neutral-600 min-h-[44px] sm:min-h-0 sm:py-1.5"
        aria-label="lock"
      >
        🔒
      </button>
    </div>
  );
}

export function Dashboard() {
  const { data: summary } = useQuery({
    queryKey: ["summary"],
    queryFn: api.summary,
    refetchInterval: 60_000,
  });

  const today = todayLocalISO();
  const { start, end } = localDayBoundsUTC(today);
  const { data: stepsToday } = useQuery({
    queryKey: ["stepsDay", today],
    queryFn: () => api.stepsDay(start, end),
    refetchInterval: 60_000,
  });

  const [browseDay, setBrowseDay] = useState<string>(today);

  return (
    <div className="max-w-6xl mx-auto px-3 sm:px-4 py-4 sm:py-8 space-y-4 sm:space-y-6 pb-24">
      <header className="flex items-center justify-between sticky top-0 z-10 bg-neutral-950/95 backdrop-blur py-2 -mx-3 px-3 sm:mx-0 sm:px-0 sm:static">
        <h1 className="text-lg sm:text-2xl font-semibold">Hack the Body</h1>
        <HeaderActions />
      </header>

      <SummaryCards summary={summary} todaySteps={stepsToday?.total} />

      <CoachCard />
      <WaterCard />
      <NotificationsCard />

      {/* Food first — it's the primary mobile use-case. */}
      <Section title="Today’s food"><TodayMeals /></Section>

      <Section
        title={`Steps · ${browseDay === today ? "today" : "browsing"}`}
        defaultOpen={false}
      >
        <StepsTodayChart onDayChange={setBrowseDay} />
      </Section>

      <Section title="Steps (30d)" defaultOpen={false}>
        <StepsChart todayLiveTotal={stepsToday?.total} />
      </Section>

      <Section title="Sleep (30d)" defaultOpen={false}><SleepChart /></Section>
      <Section title="HRV (30d)" defaultOpen={false}><HrvChart /></Section>
      <Section title="Weight (60d)" defaultOpen={false}><WeightChart /></Section>
      <Section title="Recent workouts" defaultOpen={false}><WorkoutList /></Section>
      <SyncStatusFooter />
    </div>
  );
}
