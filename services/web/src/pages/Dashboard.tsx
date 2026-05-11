import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { Summary } from "../api/types";
import { BottomNav, useActiveTab } from "../components/BottomNav";
import { ActiveWorkoutCard } from "../components/ActiveWorkoutCard";
import { CoachCard } from "../components/CoachCard";
import { HabitsCard } from "../components/HabitsCard";
import { NotificationsCard } from "../components/NotificationsCard";
import { NudgesCard } from "../components/NudgesCard";
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
import { TargetsCard } from "../components/TargetsCard";
import { TodayMeals } from "../components/TodayMeals";
import { WeightChart } from "../components/WeightChart";
import { WeightStatsCard } from "../components/WeightStatsCard";
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

/** Which Trends section to expand + scroll to when the user taps a
 *  metric card on the Today tab. `null` = no pending focus. */
type TrendFocus = "steps" | "sleep" | "weight";

function SummaryCards({ summary, onOpenTrend }: {
  summary: Summary | undefined;
  onOpenTrend?: (focus: TrendFocus) => void;
}) {
  const sleep = sleepCard(summary);
  const weight = weightCard(summary);
  return (
    <section className="grid grid-cols-2 gap-2 sm:gap-3">
      <MetricCard
        label={sleep.label} value={sleep.value} sub={sleep.sub}
        onClick={onOpenTrend ? () => onOpenTrend("sleep") : undefined}
      />
      <MetricCard
        label={weight.label} value={weight.value} sub={weight.sub}
        onClick={onOpenTrend ? () => onOpenTrend("weight") : undefined}
      />
    </section>
  );
}

function Section({ id, title, children, defaultOpen = true }: {
  id?: string; title: string; children: React.ReactNode; defaultOpen?: boolean;
}) {
  // Children are only mounted while open. Recharts' ResponsiveContainer
  // measures 0×0 when its parent is inside a collapsed <details> (native
  // display:none on the slot), which produces a runtime warning.
  const [open, setOpen] = useState(defaultOpen);
  return (
    <details
      id={id}
      open={open}
      onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}
      className="group"
    >
      <summary className="cursor-pointer list-none flex items-center justify-between text-sm uppercase tracking-wide text-neutral-400 mb-2 select-none">
        <span>{title}</span>
        <span className="text-neutral-600 group-open:rotate-90 transition-transform">▸</span>
      </summary>
      <div>{open ? children : null}</div>
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

function TodayTab({ onOpenTrend }: { onOpenTrend?: (focus: TrendFocus) => void }) {
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
      <ActiveWorkoutCard />
      <NudgesCard />
      <StepsTodayCard
        summary={summary}
        todaySteps={stepsToday?.total}
        onOpenTrends={onOpenTrend ? () => onOpenTrend("steps") : undefined}
      />
      <CoachCard />
      <WaterCard />
      <VitaminsCard />
      {/* Hides itself once granted; only shows in 'off' or 'denied'.
          Also hidden on desktop (>=md) — push from a phone/tablet is
          useful, push to a browser tab you only open at the desk is
          not. The full settings panel still lives in the More tab. */}
      <div className="md:hidden">
        <NotificationsCard />
      </div>
      <SummaryCards summary={summary} onOpenTrend={onOpenTrend} />
    </div>
  );
}

function FoodTab() {
  return <TodayMeals />;
}

/** Read the focused-section hint from the URL (`/trends?focus=steps`). */
function useTrendFocus(): TrendFocus | undefined {
  const [params] = useSearchParams();
  const f = params.get("focus");
  return f === "steps" || f === "sleep" || f === "weight" ? f : undefined;
}

function TrendsTab() {
  const focus = useTrendFocus();
  const today = todayLocalISO();
  const { start, end } = localDayBoundsUTC(today);
  const { data: stepsToday } = useQuery({
    queryKey: ["stepsDay", today],
    queryFn: () => api.stepsDay(start, end),
  });
  const [browseDay, setBrowseDay] = useState<string>(today);

  // When the user lands here from a Today-tab metric tap, force the
  // matching <details> element open and scroll it into view. Native
  // <details> open/close stays user-controllable after this.
  useEffect(() => {
    if (!focus) return;
    const id = focus === "steps" ? "trend-steps"
             : focus === "sleep" ? "trend-sleep"
             : "trend-weight";
    const el = document.getElementById(id) as HTMLDetailsElement | null;
    if (!el) return;
    el.open = true;
    requestAnimationFrame(() => {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  }, [focus]);

  return (
    <div className="space-y-4 sm:space-y-6">
      <Section
        id="trend-steps-today"
        title={`Steps · ${browseDay === today ? "today" : "browsing"}`}
        defaultOpen
      >
        <StepsTodayChart onDayChange={setBrowseDay} />
      </Section>
      <Section id="trend-steps" title="Steps (30d)" defaultOpen={focus === "steps"}>
        <StepsChart todayLiveTotal={stepsToday?.total} />
      </Section>
      <Section id="trend-sleep" title="Sleep (30d)" defaultOpen={focus === "sleep"}>
        <SleepChart />
      </Section>
      <Section title="HRV (30d)" defaultOpen={false}><HrvChart /></Section>
      <Section id="trend-weight" title="Weight (60d)" defaultOpen={focus === "weight"}>
        <div className="space-y-3">
          <WeightStatsCard />
          <WeightChart />
        </div>
      </Section>
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
      <Link
        to="/workouts"
        className="block rounded-xl bg-neutral-900 border border-neutral-800 p-4 active:bg-neutral-900/60"
      >
        <div className="flex items-center justify-between">
          <span className="font-medium">Workouts</span>
          <span className="text-neutral-600">›</span>
        </div>
        <div className="text-xs text-neutral-500 mt-1">Cardio + strength history</div>
      </Link>
      <TargetsCard />
      <HabitsCard />
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
  // Tap a Today-tab metric → push /trends?focus=<section>. Putting the
  // focus in the URL means browser back/forward, deep links, and PWA
  // refresh all do the right thing without extra plumbing.
  const navigate = useNavigate();
  const onOpenTrend = (focus: TrendFocus): void => {
    void navigate(`/trends?focus=${focus}`);
  };
  return (
    <div className="max-w-6xl mx-auto px-3 sm:px-4 py-4 sm:py-8 space-y-4 sm:space-y-6 pb-24">
      <PageHeader />
      {tab === "today"  && <TodayTab onOpenTrend={onOpenTrend} />}
      {tab === "food"   && <FoodTab />}
      {tab === "trends" && <TrendsTab />}
      {tab === "more"   && <MoreTab />}
      <BottomNav active={tab} onChange={setTab} />
    </div>
  );
}
