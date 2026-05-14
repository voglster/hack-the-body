import { describe, expect, it } from "vitest";

import {
  mealItem,
  stepsItem,
  vitaminItem,
  waterItem,
  weighInItem,
} from "./KioskOpenList";
import { todayLocalISO } from "../../lib/tz";
import type {
  MealEntry,
  Summary,
  VitaminsToday,
  WaterToday,
} from "../../api/types";

const noon = new Date(2026, 4, 14, 12, 0);
const earlyMorning = new Date(2026, 4, 14, 7, 0);
const afternoon = new Date(2026, 4, 14, 16, 0);
const evening = new Date(2026, 4, 14, 20, 0);

describe("vitaminItem", () => {
  it("null when logged", () => {
    expect(vitaminItem({ logged: true } as VitaminsToday, noon)).toBeNull();
  });
  it("null before 10am if not logged", () => {
    expect(vitaminItem({ logged: false } as VitaminsToday, earlyMorning)).toBeNull();
  });
  it("attention at noon when missing", () => {
    expect(vitaminItem({ logged: false } as VitaminsToday, noon)?.level).toBe("attention");
  });
  it("urgent in afternoon when missing", () => {
    expect(vitaminItem({ logged: false } as VitaminsToday, afternoon)?.level).toBe("urgent");
  });
});

describe("weighInItem", () => {
  it("null when today's weight present", () => {
    const today = todayLocalISO();
    const s = { weight: { ts: `${today}T07:30:00Z` } } as Summary;
    expect(weighInItem(s, noon)).toBeNull();
  });
  it("null before 9am when missing", () => {
    expect(weighInItem({ weight: null } as Summary, earlyMorning)).toBeNull();
  });
  it("urgent at noon when missing", () => {
    expect(weighInItem({ weight: null } as Summary, noon)?.level).toBe("urgent");
  });
});

describe("mealItem", () => {
  it("null before eating window", () => {
    expect(mealItem([], earlyMorning)).toBeNull();
  });
  it("attention at noon with no meals", () => {
    expect(mealItem([], noon)?.level).toBe("attention");
  });
  it("null with a recent meal", () => {
    const entries = [{ ts: new Date(2026, 4, 14, 11, 30).toISOString() }] as MealEntry[];
    expect(mealItem(entries, noon)).toBeNull();
  });
  it("attention if last meal >5h ago in eating window", () => {
    const entries = [{ ts: new Date(2026, 4, 14, 11, 0).toISOString() }] as MealEntry[];
    expect(mealItem(entries, new Date(2026, 4, 14, 17, 0))?.level).toBe("attention");
  });
  it("urgent if last meal >7h ago", () => {
    const entries = [{ ts: new Date(2026, 4, 14, 11, 0).toISOString() }] as MealEntry[];
    expect(mealItem(entries, new Date(2026, 4, 14, 19, 0))?.level).toBe("urgent");
  });
});

describe("waterItem", () => {
  it("null when target hit", () => {
    expect(waterItem({ oz: 80 } as WaterToday, 80, evening)).toBeNull();
  });
  it("attention when behind pace", () => {
    expect(waterItem({ oz: 20 } as WaterToday, 80, afternoon)?.level).toBe("attention");
  });
  it("urgent when far behind pace", () => {
    expect(waterItem({ oz: 5 } as WaterToday, 80, afternoon)?.level).toBe("urgent");
  });
});

describe("stepsItem", () => {
  it("null with no goal", () => {
    expect(stepsItem(0, null, noon)).toBeNull();
  });
  it("attention when behind pace in afternoon", () => {
    // 16:00, expected ~52%, far short of 10k
    const item = stepsItem(1000, 10000, afternoon);
    expect(item?.level).toBe("attention");
  });
  it("null when on pace", () => {
    expect(stepsItem(10000, 10000, evening)).toBeNull();
  });
});
