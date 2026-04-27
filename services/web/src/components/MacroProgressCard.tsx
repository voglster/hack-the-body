/**
 * Today's calorie progress + macro composition.
 *
 * Two stacked horizontal bars in one card:
 *  1. Calories vs daily_calories target — emerald up to target, amber for
 *     overage, red past 125%. A vertical tick marks the target itself.
 *  2. Macro composition — P/F/C as a stacked bar, segments scaled to
 *     calorie contribution (protein × 4, fat × 9, carbs × 4) so the
 *     widths reflect "share of macro calories," which is what every diet
 *     framework means by "macro split."
 *
 * No tap tooltips — exact gram numbers ride along as a static row below
 * the macro bar. See the UX brief for context on why bars over rings.
 */
import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";

const KCAL_PER_G_PROTEIN = 4;
const KCAL_PER_G_FAT = 9;
const KCAL_PER_G_CARBS = 4;

const OVER_TARGET_RED_THRESHOLD = 1.25;
const BAR_OVERHEAD_HEADROOM = 1.1;

interface CaloriesData {
  consumed: number;
  target: number;
}

interface MacroPercents {
  protein: number;
  fat: number;
  carbs: number;
}

function pct(numerator: number, denominator: number): number {
  if (!denominator) return 0;
  return Math.max(0, Math.min(100, (numerator / denominator) * 100));
}

function CalorieBar({ consumed, target }: CaloriesData) {
  // The bar's length axis is max(consumed, target * BAR_OVERHEAD_HEADROOM)
  // so a small overage is visible without yanking the layout when you blow
  // past your target by 200 kcal.
  const axisMax = Math.max(consumed, target * BAR_OVERHEAD_HEADROOM);
  const targetTickPct = (target / axisMax) * 100;
  const underTarget = Math.min(consumed, target);
  const overTarget = Math.max(0, consumed - target);
  const isWayOver = consumed > target * OVER_TARGET_RED_THRESHOLD;

  const overFill = isWayOver ? "bg-red-500" : "bg-amber-600";
  const overLabelColor = isWayOver ? "text-red-300" : "text-amber-300";

  const consumedPct = Math.round((consumed / target) * 100);
  const overSuffix = consumed > target ? " · over" : "";

  return (
    <div
      role="img"
      aria-label={`Calories: ${Math.round(consumed)} of ${Math.round(target)} kcal, ${consumedPct} percent${consumed > target ? " over target" : ""}`}
    >
      <div className="flex items-baseline justify-between mb-1.5 text-xs">
        <span className="uppercase tracking-wide text-neutral-400">Calories</span>
        <span className={`tabular-nums ${consumed > target ? overLabelColor : "text-neutral-300"}`}>
          {Math.round(consumed).toLocaleString()} / {Math.round(target).toLocaleString()}
          <span className="text-neutral-500"> · {consumedPct}%{overSuffix}</span>
        </span>
      </div>
      <div className="relative h-4 w-full rounded-full bg-neutral-800 overflow-hidden">
        <div className="flex h-full">
          <div
            className="h-full bg-emerald-600"
            style={{ width: `${(underTarget / axisMax) * 100}%` }}
          />
          {overTarget > 0 && (
            <div
              className={`h-full ${overFill}`}
              style={{ width: `${(overTarget / axisMax) * 100}%` }}
            />
          )}
        </div>
        <div
          className="absolute top-0 bottom-0 w-px bg-white/60"
          style={{ left: `${targetTickPct}%` }}
          aria-hidden
        />
      </div>
    </div>
  );
}

function MacroStack({ protein, fat, carbs, gramsP, gramsF, gramsC }: MacroPercents & {
  gramsP: number;
  gramsF: number;
  gramsC: number;
}) {
  const segments = [
    { key: "protein", label: "P", percent: protein, color: "bg-emerald-600", textColor: "text-emerald-50" },
    { key: "fat", label: "F", percent: fat, color: "bg-amber-600", textColor: "text-amber-50" },
    { key: "carbs", label: "C", percent: carbs, color: "bg-sky-600", textColor: "text-sky-50" },
  ];

  return (
    <div
      role="img"
      aria-label={`Macros: protein ${Math.round(protein)} percent, fat ${Math.round(fat)} percent, carbs ${Math.round(carbs)} percent`}
    >
      <div className="flex items-baseline justify-between mb-1.5 text-xs">
        <span className="uppercase tracking-wide text-neutral-400">Macros</span>
        <span className="text-neutral-500 tabular-nums">
          P {Math.round(protein)}% · F {Math.round(fat)}% · C {Math.round(carbs)}%
        </span>
      </div>
      <div className="flex h-4 w-full rounded-full bg-neutral-800 overflow-hidden">
        {segments.map(seg => seg.percent > 0 && (
          <div
            key={seg.key}
            className={`h-full ${seg.color} flex items-center justify-center text-[10px] font-medium ${seg.textColor}`}
            style={{ width: `${seg.percent}%` }}
            // Hide the inline letter when the segment is too narrow to read.
            // 12% threshold matches roughly 40 px on a 360 px screen.
          >
            {seg.percent >= 12 ? seg.label : ""}
          </div>
        ))}
      </div>
      <div className="mt-1 text-[11px] text-neutral-500 tabular-nums">
        P {Math.round(gramsP)}g · F {Math.round(gramsF)}g · C {Math.round(gramsC)}g
      </div>
    </div>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-4 space-y-4">
      <div className="text-xs uppercase tracking-wide text-neutral-400">Today</div>
      {children}
    </div>
  );
}

export function MacroProgressCard() {
  const totals = useQuery({
    queryKey: ["meals.today.totals"],
    queryFn: api.todayTotals,
    refetchInterval: 60_000,
  });
  const targets = useQuery({
    queryKey: ["profile.targets"],
    queryFn: api.getTargets,
  });

  // While loading, render the card shell so the layout doesn't jump.
  if (!totals.data || !targets.data) {
    return <Card><div className="h-16" /></Card>;
  }

  const t = totals.data.totals;
  const targetCal = targets.data.daily_calories ?? null;
  const consumedCal = t.calories;

  const proteinKcal = (t.protein_g || 0) * KCAL_PER_G_PROTEIN;
  const fatKcal = (t.fat_g || 0) * KCAL_PER_G_FAT;
  const carbKcal = (t.carbs_g || 0) * KCAL_PER_G_CARBS;
  const macroKcal = proteinKcal + fatKcal + carbKcal;
  const noMacros = macroKcal <= 0;

  const macros: MacroPercents = noMacros
    ? { protein: 0, fat: 0, carbs: 0 }
    : {
        protein: pct(proteinKcal, macroKcal),
        fat: pct(fatKcal, macroKcal),
        carbs: pct(carbKcal, macroKcal),
      };

  return (
    <Card>
      {targetCal != null && targetCal > 0 ? (
        <CalorieBar consumed={consumedCal} target={targetCal} />
      ) : (
        <div className="text-xs text-neutral-400">
          {Math.round(consumedCal).toLocaleString()} kcal today
          <span className="text-neutral-600"> · no calorie target set</span>
        </div>
      )}
      {noMacros ? (
        <div className="text-sm text-neutral-500">Log a meal to see your macro split</div>
      ) : (
        <MacroStack
          {...macros}
          gramsP={t.protein_g || 0}
          gramsF={t.fat_g || 0}
          gramsC={t.carbs_g || 0}
        />
      )}
    </Card>
  );
}
