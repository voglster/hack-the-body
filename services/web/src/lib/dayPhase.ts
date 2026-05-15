/** Phase-of-day for the kiosk's rest-state card. Phases are
 *  time-anchored and tied to a default bedtime of 22:45 local. */

export type DayPhase = "pre-sunlight" | "sunlight" | "movement" | "wind-down" | "late";

const BEDTIME_HOUR = 22;
const BEDTIME_MIN = 45;
const WIND_DOWN_LEAD_MIN = 90;
const SUNLIGHT_END_HOUR = 10;
const SUNLIGHT_START_HOUR = 6;

function asMinutes(h: number, m: number): number {
  return h * 60 + m;
}

function nowMinutes(d: Date): number {
  return d.getHours() * 60 + d.getMinutes();
}

export function currentPhase(now: Date = new Date()): DayPhase {
  const m = nowMinutes(now);
  const bedtime = asMinutes(BEDTIME_HOUR, BEDTIME_MIN);
  const windDownStart = bedtime - WIND_DOWN_LEAD_MIN;
  const sunlightStart = asMinutes(SUNLIGHT_START_HOUR, 0);
  const sunlightEnd = asMinutes(SUNLIGHT_END_HOUR, 0);

  if (m < sunlightStart) return "pre-sunlight";
  if (m < sunlightEnd) return "sunlight";
  if (m < windDownStart) return "movement";
  if (m < bedtime) return "wind-down";
  return "late";
}

export interface PhaseInfo {
  phase: DayPhase;
  title: string;       // e.g. "SUNLIGHT WINDOW"
  detail: string;      // e.g. "22 min left"
  /** True when the screen should adopt the warm/dim wind-down palette. */
  windDownMode: boolean;
}

function minutesLeftIn(now: Date, hour: number, minute: number): number {
  const target = asMinutes(hour, minute);
  return Math.max(0, target - nowMinutes(now));
}

export function phaseInfo(now: Date = new Date()): PhaseInfo {
  const phase = currentPhase(now);
  switch (phase) {
    case "pre-sunlight":
      return {
        phase, windDownMode: false,
        title: "SUNLIGHT WINDOW",
        detail: `opens at ${SUNLIGHT_START_HOUR}:00`,
      };
    case "sunlight": {
      const left = minutesLeftIn(now, SUNLIGHT_END_HOUR, 0);
      return {
        phase, windDownMode: false,
        title: "SUNLIGHT WINDOW",
        detail: `${left} min left · step outside`,
      };
    }
    case "movement":
      return {
        phase, windDownMode: false,
        title: "MOVEMENT WINDOW",
        detail: "stack the steps",
      };
    case "wind-down": {
      const left = minutesLeftIn(now, BEDTIME_HOUR, BEDTIME_MIN);
      return {
        phase, windDownMode: true,
        title: "WIND DOWN",
        detail: `lights out in ${left} min`,
      };
    }
    case "late":
      return {
        phase, windDownMode: true,
        title: "PAST BEDTIME",
        detail: "tomorrow is built tonight",
      };
  }
}
