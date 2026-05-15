import { describe, expect, it } from "vitest";

import { stepStreak } from "./stepStreak";
import type { DailySummaryPoint } from "../api/types";

function day(ts: string, steps: number, goal: number | null = 10000): DailySummaryPoint {
  return {
    ts,
    steps,
    step_goal: goal,
    distance_m: null,
    active_kcal: null,
    total_kcal: null,
    resting_hr: null,
    intensity_minutes: null,
    floors_climbed: null,
  };
}

describe("stepStreak", () => {
  it("empty input → 0/0", () => {
    expect(stepStreak([])).toEqual({ current: 0, longest: 0 });
  });

  it("all hits", () => {
    const h = [
      day("2026-05-10", 12000),
      day("2026-05-11", 12000),
      day("2026-05-12", 12000),
    ];
    expect(stepStreak(h)).toEqual({ current: 3, longest: 3 });
  });

  it("all misses", () => {
    const h = [
      day("2026-05-10", 100),
      day("2026-05-11", 100),
      day("2026-05-12", 100),
    ];
    expect(stepStreak(h)).toEqual({ current: 0, longest: 0 });
  });

  it("single miss in middle is forgiven", () => {
    const h = [
      day("2026-05-10", 12000),
      day("2026-05-11", 100), // forgiven
      day("2026-05-12", 12000),
      day("2026-05-13", 12000),
    ];
    expect(stepStreak(h)).toEqual({ current: 3, longest: 3 });
  });

  it("two consecutive misses resets streak", () => {
    const h = [
      day("2026-05-10", 12000),
      day("2026-05-11", 12000),
      day("2026-05-12", 100),
      day("2026-05-13", 100),
      day("2026-05-14", 12000),
    ];
    expect(stepStreak(h)).toEqual({ current: 1, longest: 2 });
  });

  it("miss-hit-miss survives", () => {
    const h = [
      day("2026-05-10", 12000),
      day("2026-05-11", 100), // forgiven
      day("2026-05-12", 12000),
      day("2026-05-13", 100), // forgiven again
    ];
    expect(stepStreak(h)).toEqual({ current: 2, longest: 2 });
  });

  it("null goal treats day as miss", () => {
    const h = [
      day("2026-05-10", 12000),
      day("2026-05-11", 99999, null),
      day("2026-05-12", 99999, null),
    ];
    expect(stepStreak(h)).toEqual({ current: 0, longest: 1 });
  });
});
