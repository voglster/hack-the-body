import { describe, expect, it } from "vitest";
import { formatDuration, formatKg, formatLbs, kgToLbs } from "../format";

describe("format", () => {
  it("kg to lbs", () => {
    expect(kgToLbs(108.9)).toBeCloseTo(240.08, 1);
  });
  it("formatKg", () => {
    expect(formatKg(108.9)).toBe("108.9 kg");
  });
  it("formatLbs", () => {
    expect(formatLbs(108.9)).toBe("240.1 lb");
  });
  it("formatDuration", () => {
    expect(formatDuration(7 * 3600 + 15 * 60)).toBe("7h 15m");
    expect(formatDuration(59 * 60)).toBe("59m");
  });
});
