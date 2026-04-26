import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { Summary } from "../api/types";
import { BottomNav, useActiveTab } from "../components/BottomNav";
import { CoachCard } from "../components/CoachCard";
import { NotificationsCard } from "../components/NotificationsCard";
import { NotificationsSettings } from "../components/NotificationsSettings";
import { VitaminsCard } from "../components/VitaminsCard";
import { WaterCard } from "../components/WaterCard";
import { HrvChart } from "../components/HrvChart";
import { MetricCard } from "../components/MetricCard";
import { SleepChart } from "../components/SleepChart";
import { StepsChart } from "../components/StepsChart";
import { StepsTodayCard } from "../components/StepsTodayCard";
import { StepsTodayChart } from "../components/StepsTodayChart";
import { SyncDot } from "../components/SyncDot";
import { TodayMeals } from "../components/TodayMeals";
import { WeightChart } from "../components/WeightChart";
import { WorkoutList } from "../components/WorkoutList";
import { clearApiKey } from "../lib/auth";
import { formatDuration, formatLbs } from "../lib/format";
import { localDayBoundsUTC, todayLocalISO } from "../lib/tz";

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

function SummaryCards({ summary }: { summary: Summary | undefined }) {
  const cards = [sleepCard(summary), weightCard(summary)];
  return (
    <section className="grid grid-cols-2 gap-2 sm:gap-3">
      {cards.map(c => (
        <MetricCard key={c.label} label={c.label} value={c.value} sub={c.sub} />
      ))}
    </section>
  );
}

function Section({ title, children, defaultOpen = true }: {
  title: string; children: React.ReactNode; defaultOpen?: boolean;
}) {
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
    <div className="flex items-center gap-1">
      <SyncDot />
      <button
        onClick={() => sync.mutate()}
        disabled={sync.isPending}
        className="text-xs px-3 py-2 rounded bg-neutral-800 hover:bg-neutral-700 active:bg-neutral-600 disabled:opacity-50 min-h-[44px] sm:min-h-0 sm:py-1.5"
        aria-label="trigger garmin sync"
      >
        {sync.isPending ? "..." : "↻"}
      </button>
    </div>
  );
}

function PageHeader() {
  return (
    <header className="flex items-center justify-between sticky top-0 z-10 bg-neutral-950/95 backdrop-blur py-2 -mx-3 px-3 sm:mx-0 sm:px-0 sm:static">
      <h1 className="text-lg sm:text-2xl font-semibold">Hack the Body</h1>
      <HeaderActions />
    </header>
  );
}

function TodayTab() {
  const { data: summary } = useQuery({
    queryKey: ["summary"], queryFn: api.summary, refetchInterval: 60_000,
  });
  const today = todayLocalISO();
  const { start, end } = localDayBoundsUTC(today);
  const { data: stepsToday } = useQuery({
    queryKey: ["stepsDay", today],
    queryFn: () => api.stepsDay(start, end),
    refetchInterval: 60_000,
  });

  return (
    <div className="space-y-4 sm:space-y-6">
      <StepsTodayCard summary={summary} todaySteps={stepsToday?.total} />
      <CoachCard />
      <WaterCard />
      <VitaminsCard />
      {/* Hides itself once granted; only shows in 'off' or 'denied'. */}
      <NotificationsCard />
      <SummaryCards summary={summary} />
    </div>
  );
}

function FoodTab() {
  return <TodayMeals />;
}

function TrendsTab() {
  const today = todayLocalISO();
  const { start, end } = localDayBoundsUTC(today);
  const { data: stepsToday } = useQuery({
    queryKey: ["stepsDay", today],
    queryFn: () => api.stepsDay(start, end),
  });
  const [browseDay, setBrowseDay] = useState<string>(today);

  return (
    <div className="space-y-4 sm:space-y-6">
      <Section
        title={`Steps · ${browseDay === today ? "today" : "browsing"}`}
        defaultOpen
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
    </div>
  );
}

function MoreTab() {
  const qc = useQueryClient();
  const clearCache = useMutation({
    mutationFn: api.clearFoodCache,
  });
  const onClearCache = () => {
    if (!confirm(
      "Clear cached food lookups (OFF/USDA)? Manual foods, water, vitamins, and template-referenced foods are kept.",
    )) return;
    clearCache.mutate(undefined, {
      onSuccess: (r) => {
        alert(`Cleared ${r.deleted} cached foods.`);
        void qc.invalidateQueries({ queryKey: ["meals.today.entries"] });
      },
    });
  };

  return (
    <div className="space-y-4 sm:space-y-6">
      <NotificationsSettings />
      <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-4 space-y-2">
        <div className="text-xs uppercase tracking-wide text-neutral-400">Maintenance</div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={onClearCache}
            disabled={clearCache.isPending}
            className="px-3 py-2 rounded bg-neutral-800 active:bg-neutral-700 text-sm disabled:opacity-50 min-h-[44px]"
          >
            {clearCache.isPending ? "clearing..." : "refresh food cache"}
          </button>
        </div>
      </div>
      <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-4 space-y-2">
        <div className="text-xs uppercase tracking-wide text-neutral-400">Session</div>
        <button
          onClick={() => clearApiKey()}
          className="px-3 py-2 rounded bg-neutral-800 active:bg-neutral-700 text-sm min-h-[44px]"
        >
          🔒 lock
        </button>
      </div>
    </div>
  );
}

export function Dashboard() {
  const [tab, setTab] = useActiveTab();
  return (
    <div className="max-w-6xl mx-auto px-3 sm:px-4 py-4 sm:py-8 space-y-4 sm:space-y-6 pb-24">
      <PageHeader />
      {tab === "today"  && <TodayTab />}
      {tab === "food"   && <FoodTab />}
      {tab === "trends" && <TrendsTab />}
      {tab === "more"   && <MoreTab />}
      <BottomNav active={tab} onChange={setTab} />
    </div>
  );
}
