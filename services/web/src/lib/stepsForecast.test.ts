import { describe, expect, it } from "vitest";

import { expectedFractionAt, forecast } from "./stepsForecast";

describe("expectedFractionAt", () => {
  it("returns near 0 in early morning", () => {
    const t = new Date(2026, 4, 14, 6, 0);
    expect(expectedFractionAt(t)).toBeCloseTo(0.02, 2);
  });
  it("returns 1.0 at end of day", () => {
    const t = new Date(2026, 4, 14, 23, 59);
    expect(expectedFractionAt(t)).toBeCloseTo(1.0, 1);
  });
});

describe("forecast", () => {
  it("returns no-goal when goal is null", () => {
    const f = forecast(1000, null, new Date(2026, 4, 14, 12, 0));
    expect(f.status).toBe("no-goal");
  });
  it("marks behind when far below expected at midday", () => {
    const f = forecast(500, 10_000, new Date(2026, 4, 14, 14, 0));
    expect(f.status).toBe("behind");
    expect(f.needPerHour).toBeGreaterThan(0);
  });
  it("marks ahead or on-pace when well above expected at midday", () => {
    const f = forecast(9_000, 10_000, new Date(2026, 4, 14, 12, 0));
    expect(["ahead", "on-pace"]).toContain(f.status);
  });
});
