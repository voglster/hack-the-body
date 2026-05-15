import { describe, expect, it } from "vitest";

import { currentPhase, phaseInfo } from "./dayPhase";

function at(h: number, m: number): Date {
  return new Date(2026, 4, 14, h, m);
}

describe("currentPhase", () => {
  it("05:59 → pre-sunlight", () => {
    expect(currentPhase(at(5, 59))).toBe("pre-sunlight");
  });
  it("06:00 → sunlight", () => {
    expect(currentPhase(at(6, 0))).toBe("sunlight");
  });
  it("09:59 → sunlight", () => {
    expect(currentPhase(at(9, 59))).toBe("sunlight");
  });
  it("10:00 → movement", () => {
    expect(currentPhase(at(10, 0))).toBe("movement");
  });
  it("21:14 → movement", () => {
    expect(currentPhase(at(21, 14))).toBe("movement");
  });
  it("21:15 → wind-down", () => {
    expect(currentPhase(at(21, 15))).toBe("wind-down");
  });
  it("22:44 → wind-down", () => {
    expect(currentPhase(at(22, 44))).toBe("wind-down");
  });
  it("22:45 → late", () => {
    expect(currentPhase(at(22, 45))).toBe("late");
  });
});

describe("phaseInfo.windDownMode", () => {
  it("false for pre-sunlight", () => {
    expect(phaseInfo(at(3, 0)).windDownMode).toBe(false);
  });
  it("false for sunlight", () => {
    expect(phaseInfo(at(7, 0)).windDownMode).toBe(false);
  });
  it("false for movement", () => {
    expect(phaseInfo(at(15, 0)).windDownMode).toBe(false);
  });
  it("true for wind-down", () => {
    expect(phaseInfo(at(21, 30)).windDownMode).toBe(true);
  });
  it("true for late", () => {
    expect(phaseInfo(at(23, 30)).windDownMode).toBe(true);
  });
});

describe("phaseInfo sunlight detail", () => {
  it("at 09:30 reports 30 min left", () => {
    expect(phaseInfo(at(9, 30)).detail).toContain("30 min left");
  });
  it("at 06:00 reports 240 min left", () => {
    expect(phaseInfo(at(6, 0)).detail).toContain("240 min left");
  });
});
