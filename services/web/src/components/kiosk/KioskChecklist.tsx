import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";
import { expectedFractionAt } from "../../lib/stepsForecast";
import { todayLocalISO } from "../../lib/tz";
import type { MealEntry, Summary, VitaminsToday, WaterToday } from "../../api/types";

export type Status = "done" | "attention" | "neutral";

export function vitaminStatus(v: VitaminsToday | undefined, now: Date): Status {
  if (v?.logged) return "done";
  return now.getHours() >= 10 ? "attention" : "neutral";
}

export function weighInStatus(summary: Summary | undefined, now: Date): Status {
  const today = todayLocalISO();
  const wts = summary?.weight?.ts;
  if (wts && wts.slice(0, 10) === today) return "done";
  return now.getHours() >= 9 ? "attention" : "neutral";
}

export function lastMealStatus(
  entries: MealEntry[] | undefined,
  now: Date,
): { status: Status; label: string } {
  if (now.getHours() < 9) return { status: "neutral", label: "—" };
  if (!entries || entries.length === 0) {
    const inEatingWindow = now.getHours() >= 11 && now.getHours() < 21;
    return { status: inEatingWindow ? "attention" : "neutral", label: "none yet" };
  }
  const latest = entries.reduce((a, b) => (a.ts > b.ts ? a : b));
  const d = new Date(latest.ts);
  const label = d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  const ageH = (now.getTime() - d.getTime()) / 3_600_000;
  const inEatingWindow = now.getHours() >= 11 && now.getHours() < 21;
  const status: Status =
    ageH > 5 && inEatingWindow ? "attention" : "done";
  return { status, label };
}

export function waterStatus(
  water: WaterToday | undefined,
  targetOz: number,
  now: Date,
): { status: Status; label: string } {
  const oz = water?.oz ?? 0;
  const label = `${Math.round(oz)} / ${targetOz} oz`;
  if (oz >= targetOz) return { status: "done", label };
  const expectedFrac = expectedFractionAt(now);
  const haveFrac = oz / targetOz;
  if (expectedFrac - haveFrac > 0.2) return { status: "attention", label };
  return { status: "neutral", label };
}

function Glyph({ status }: { status: Status }) {
  if (status === "done") return <span className="text-emerald-400">✓</span>;
  if (status === "attention") return <span className="text-amber-400">!</span>;
  return <span className="text-neutral-600">—</span>;
}

function Row({
  icon, label, status, value,
}: {
  icon: string;
  label: string;
  status: Status;
  value?: string;
}) {
  return (
    <div className="flex items-center gap-4 py-2">
      <span className="text-3xl w-10 text-center">{icon}</span>
      <span className="text-xl flex-1">{label}</span>
      {value && <span className="text-lg text-neutral-400 tabular-nums">{value}</span>}
      <span className="text-3xl w-8 text-center"><Glyph status={status} /></span>
    </div>
  );
}

export function KioskChecklist() {
  const summaryQ = useQuery({
    queryKey: ["summary"], queryFn: api.summary, refetchInterval: 5 * 60_000,
  });
  const vitaminsQ = useQuery({
    queryKey: ["vitamins-today"], queryFn: api.vitaminsToday, refetchInterval: 60_000,
  });
  const waterQ = useQuery({
    queryKey: ["water-today"], queryFn: api.waterToday, refetchInterval: 60_000,
  });
  const entriesQ = useQuery({
    queryKey: ["today-entries"], queryFn: () => api.todayEntries(), refetchInterval: 60_000,
  });
  const targetsQ = useQuery({
    queryKey: ["targets"], queryFn: api.getTargets,
  });

  const now = new Date();
  const targetOz = targetsQ.data?.daily_water_oz ?? 80;
  const meal = lastMealStatus(entriesQ.data, now);
  const water = waterStatus(waterQ.data, targetOz, now);

  return (
    <section className="rounded-2xl border border-neutral-800 bg-neutral-950 p-8">
      <div className="text-xs uppercase tracking-widest text-neutral-500 mb-3">
        Today
      </div>
      <Row icon="💊" label="Vitamins"
           status={vitaminStatus(vitaminsQ.data, now)} />
      <Row icon="⚖️" label="Weigh in"
           status={weighInStatus(summaryQ.data, now)} />
      <Row icon="🍽" label="Last meal" value={meal.label} status={meal.status} />
      <Row icon="💧" label="Water" value={water.label} status={water.status} />
    </section>
  );
}
