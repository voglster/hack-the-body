/**
 * Heart-rate zone helpers.
 *
 * Static thresholds for v1 — match the API aggregator's `HR_ZONES` so
 * client labels line up with the time-in-zone the backend computes.
 * Once we wire user profile age + measured RHR into a Karvonen-based
 * personal calculation we'll thread that through here.
 */

export type ZoneKey = "z1" | "z2" | "z3" | "z4" | "z5";

export interface ZoneDef {
  key: ZoneKey;
  /** UI label. Aligned with consumer treadmill conventions
   *  (warm-up / fat-burn / cardio / threshold / peak). */
  label: string;
  /** Inclusive lower bpm bound. */
  lo: number;
  /** Exclusive upper bpm bound. */
  hi: number;
  /** Tailwind text/bg classes for the zone color. */
  textClass: string;
  bgClass: string;
  borderClass: string;
}

export const HR_ZONES: ZoneDef[] = [
  { key: "z1", label: "Warm-up",   lo: 0,   hi: 110,
    textClass: "text-sky-300",     bgClass: "bg-sky-500",     borderClass: "border-sky-700/50" },
  { key: "z2", label: "Fat burn",  lo: 110, hi: 130,
    textClass: "text-emerald-300", bgClass: "bg-emerald-500", borderClass: "border-emerald-700/50" },
  { key: "z3", label: "Cardio",    lo: 130, hi: 150,
    textClass: "text-amber-300",   bgClass: "bg-amber-500",   borderClass: "border-amber-700/50" },
  { key: "z4", label: "Threshold", lo: 150, hi: 170,
    textClass: "text-orange-300",  bgClass: "bg-orange-500",  borderClass: "border-orange-700/50" },
  { key: "z5", label: "Peak",      lo: 170, hi: 999,
    textClass: "text-red-300",     bgClass: "bg-red-500",     borderClass: "border-red-700/50" },
];

/** Default fat-loss target. The 60-70% max-HR window for an "average"
 *  middle-age adult lands roughly here; configurable later via profile. */
export const DEFAULT_TARGET_ZONE: ZoneKey = "z2";

export function zoneForHr(hr: number | null | undefined): ZoneDef | null {
  if (hr == null || hr <= 0) return null;
  return HR_ZONES.find(z => hr >= z.lo && hr < z.hi) ?? null;
}

/** Plain-english adjustment hint comparing the current HR to a target zone.
 *  Returns null if there's not enough info to make a call. */
export function zoneAdvice(
  currentHr: number | null | undefined,
  currentSpeed: number | null | undefined,
  target: ZoneKey = DEFAULT_TARGET_ZONE,
): string | null {
  const z = zoneForHr(currentHr);
  if (!z) return null;
  const tz = HR_ZONES.find(t => t.key === target);
  if (!tz) return null;
  if (z.key === target) return `On target — ${tz.label.toLowerCase()} zone, hold this pace.`;
  const above = HR_ZONES.indexOf(z) > HR_ZONES.indexOf(tz);
  const speedTxt = currentSpeed != null && currentSpeed > 0
    ? ` from ${currentSpeed.toFixed(1)} mph`
    : "";
  if (above) {
    return `Above ${tz.label.toLowerCase()} (in ${z.label}). Drop ~0.3 mph${speedTxt} to settle into target.`;
  }
  return `Below ${tz.label.toLowerCase()} (in ${z.label}). Bump ~0.2 mph${speedTxt} to lift HR into target.`;
}
