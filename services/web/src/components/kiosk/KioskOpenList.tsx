import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";
import { localDayBoundsUTC, todayLocalISO } from "../../lib/tz";
import type { StepsToday, UserTargets } from "../../api/types";
import {
  mealItem,
  proteinItem,
  stepsItem,
  vitaminItem,
  waterItem,
  weighInItem,
  type OpenItem,
} from "./kioskOpenItems";

const DOT_COLOR: Record<OpenItem["level"], string> = {
  attention: "bg-amber-400",
  urgent: "bg-red-500",
};

function Row({ item }: { item: OpenItem }) {
  return (
    <div className="flex items-center gap-6 text-[3.5rem] font-medium leading-tight">
      <span className={`w-4 h-4 rounded-full ${DOT_COLOR[item.level]} shrink-0`} />
      <span className="text-white flex-1">{item.label}</span>
      {item.value && (
        <span className="text-neutral-400 tabular-nums">{item.value}</span>
      )}
    </div>
  );
}

export function KioskOpenList() {
  const summaryQ = useQuery({
    queryKey: ["summary"],
    queryFn: api.summary,
    refetchInterval: 5 * 60_000,
  });
  const vitaminsQ = useQuery({
    queryKey: ["vitamins-today"],
    queryFn: api.vitaminsToday,
    refetchInterval: 60_000,
  });
  const waterQ = useQuery({
    queryKey: ["water-today"],
    queryFn: api.waterToday,
    refetchInterval: 60_000,
  });
  const entriesQ = useQuery({
    queryKey: ["today-entries"],
    queryFn: () => api.todayEntries(),
    refetchInterval: 60_000,
  });
  const targetsQ = useQuery<UserTargets>({
    queryKey: ["targets"],
    queryFn: api.getTargets,
  });
  const stepsQ = useQuery<StepsToday>({
    queryKey: ["steps-today"],
    queryFn: () => {
      const { start, end } = localDayBoundsUTC(todayLocalISO());
      return api.stepsDay(start, end);
    },
    refetchInterval: 60_000,
  });
  const totalsQ = useQuery({
    queryKey: ["today-totals"],
    queryFn: () => api.todayTotals(),
    refetchInterval: 60_000,
  });

  const now = new Date();
  const targetOz = targetsQ.data?.daily_water_oz ?? 80;
  const targetProteinG = targetsQ.data?.daily_protein_g ?? 180;
  const stepGoal = summaryQ.data?.daily_summary?.step_goal ?? null;
  const stepsCount = stepsQ.data?.total ?? 0;

  const items: (OpenItem | null)[] = [
    vitaminItem(vitaminsQ.data, now),
    weighInItem(summaryQ.data, now),
    mealItem(entriesQ.data, now),
    waterItem(waterQ.data, targetOz, now),
    proteinItem(totalsQ.data, targetProteinG, now),
    stepsItem(stepsCount, stepGoal, now),
  ];
  const open = items.filter((i): i is OpenItem => i !== null);

  if (open.length === 0) return null;

  return (
    <section className="flex flex-col gap-6">
      {open.map((item) => (
        <Row key={item.key} item={item} />
      ))}
    </section>
  );
}
