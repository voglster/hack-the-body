import { describe, expect, it } from "vitest";

import {
  lastMealStatus,
  vitaminStatus,
  waterStatus,
  weighInStatus,
} from "./KioskChecklist";
import { todayLocalISO } from "../../lib/tz";
import type { MealEntry, Summary, VitaminsToday, WaterToday } from "../../api/types";

const noon = new Date(2026, 4, 14, 12, 0);
const earlyMorning = new Date(2026, 4, 14, 7, 0);
const evening = new Date(2026, 4, 14, 20, 0);

describe("vitaminStatus", () => {
  it("done when logged", () => {
    expect(vitaminStatus({ logged: true } as VitaminsToday, noon)).toBe("done");
  });
  it("neutral before 10am if not logged", () => {
    expect(vitaminStatus({ logged: false } as VitaminsToday, earlyMorning)).toBe("neutral");
  });
  it("attention after 10am if not logged", () => {
    expect(vitaminStatus({ logged: false } as VitaminsToday, noon)).toBe("attention");
  });
});

describe("weighInStatus", () => {
  it("done when today's weight present", () => {
    const today = todayLocalISO();
    const s = { weight: { ts: `${today}T07:30:00Z` } } as Summary;
    expect(weighInStatus(s, noon)).toBe("done");
  });
  it("attention after 9am when missing", () => {
    expect(weighInStatus({ weight: null } as Summary, noon)).toBe("attention");
  });
});

describe("lastMealStatus", () => {
  it("neutral before 9am", () => {
    expect(lastMealStatus([], earlyMorning).status).toBe("neutral");
  });
  it("attention in eating window with no meals", () => {
    expect(lastMealStatus([], noon).status).toBe("attention");
  });
  it("done with a recent meal", () => {
    const entries = [{ ts: new Date(2026, 4, 14, 11, 30).toISOString() }] as MealEntry[];
    expect(lastMealStatus(entries, noon).status).toBe("done");
  });
  it("attention if last meal >5h ago in eating window", () => {
    const entries = [{ ts: new Date(2026, 4, 14, 11, 0).toISOString() }] as MealEntry[];
    expect(lastMealStatus(entries, new Date(2026, 4, 14, 17, 0)).status).toBe("attention");
  });
});

describe("waterStatus", () => {
  it("done when target hit", () => {
    expect(waterStatus({ oz: 80 } as WaterToday, 80, evening).status).toBe("done");
  });
  it("attention when far behind pace", () => {
    const afternoon = new Date(2026, 4, 14, 16, 0);
    expect(waterStatus({ oz: 10 } as WaterToday, 80, afternoon).status).toBe("attention");
  });
});
