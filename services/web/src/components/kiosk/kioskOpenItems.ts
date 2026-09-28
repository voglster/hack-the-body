import { expectedFractionAt, forecast } from "../../lib/stepsForecast";
import { todayLocalISO } from "../../lib/tz";
import type {
  MealEntry,
  Summary,
  TodayTotals,
  VitaminsToday,
  WaterToday,
} from "../../api/types";

export interface OpenItem {
  key: string;
  label: string;
  value?: string;
  level: "attention" | "urgent";
}

export function vitaminItem(v: VitaminsToday | undefined, now: Date): OpenItem | null {
  if (v?.logged) return null;
  if (now.getHours() < 10) return null;
  return {
    key: "vitamins",
    label: "VITAMINS",
    level: now.getHours() >= 14 ? "urgent" : "attention",
  };
}

export function weighInItem(summary: Summary | undefined, now: Date): OpenItem | null {
  const today = todayLocalISO();
  const wts = summary?.weight?.ts;
  if (wts?.slice(0, 10) === today) return null;
  if (now.getHours() < 9) return null;
  return {
    key: "weigh-in",
    label: "WEIGH IN",
    level: now.getHours() >= 12 ? "urgent" : "attention",
  };
}

export function mealItem(
  entries: MealEntry[] | undefined,
  now: Date,
): OpenItem | null {
  if (now.getHours() < 11 || now.getHours() >= 21) return null;
  if (!entries || entries.length === 0) {
    return {
      key: "meal",
      label: "LOG FOOD",
      value: "none yet",
      level: now.getHours() >= 14 ? "urgent" : "attention",
    };
  }
  const latest = entries.reduce((a, b) => (a.ts > b.ts ? a : b));
  const ageH = (now.getTime() - new Date(latest.ts).getTime()) / 3_600_000;
  if (ageH > 5) {
    const last = new Date(latest.ts).toLocaleTimeString([], {
      hour: "numeric",
      minute: "2-digit",
    });
    return {
      key: "meal",
      label: "EAT",
      value: `last ${last}`,
      level: ageH > 7 ? "urgent" : "attention",
    };
  }
  return null;
}

export function waterItem(
  water: WaterToday | undefined,
  targetOz: number,
  now: Date,
): OpenItem | null {
  const oz = water?.oz ?? 0;
  if (oz >= targetOz) return null;
  const expectedFrac = expectedFractionAt(now);
  const haveFrac = oz / targetOz;
  const gap = expectedFrac - haveFrac;
  if (gap <= 0.2) return null;
  return {
    key: "water",
    label: "WATER",
    value: `${Math.round(oz)} / ${targetOz} oz`,
    level: gap > 0.4 ? "urgent" : "attention",
  };
}

export function stepsItem(
  steps: number,
  goal: number | null,
  now: Date,
): OpenItem | null {
  if (!goal) return null;
  const f = forecast(steps, goal, now);
  if (f.status === "behind" || f.status === "miss") {
    return {
      key: "steps",
      label: "WALK",
      value: `${steps.toLocaleString()} / ${goal.toLocaleString()}`,
      level: f.status === "miss" ? "urgent" : "attention",
    };
  }
  return null;
}

export function proteinItem(
  todayTotals: TodayTotals | undefined,
  targetG: number,
  now: Date,
): OpenItem | null {
  if (now.getHours() < 11) return null; // eating window not open yet
  const g = todayTotals?.totals?.protein_g ?? 0;
  if (g >= targetG) return null;
  const expectedFrac = expectedFractionAt(now);
  const haveFrac = g / targetG;
  const gap = expectedFrac - haveFrac;
  if (gap <= 0.15) return null;
  return {
    key: "protein",
    label: "PROTEIN",
    value: `${Math.round(g)} / ${targetG} g`,
    level: gap > 0.4 ? "urgent" : "attention",
  };
}
