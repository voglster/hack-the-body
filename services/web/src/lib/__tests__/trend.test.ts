import { describe, expect, it } from "vitest";
import { ratePerWeek, rollingAverage } from "../trend";

describe("rollingAverage", () => {
  it("empty", () => {
    expect(rollingAverage([], 7)).toEqual([]);
  });
  it("window fills as data accumulates", () => {
    const pts = [
      { ts: "2026-01-01", value: 100 },
      { ts: "2026-01-02", value: 102 },
      { ts: "2026-01-03", value: 104 },
    ];
    const out = rollingAverage(pts, 3);
    expect(out[2].avg).toBeCloseTo(102, 5);
    expect(out[0].avg).toBeCloseTo(100, 5);
  });
});

describe("ratePerWeek", () => {
  const NOW = new Date("2026-05-03T00:00:00Z");
  const dayAgo = (n: number) =>
    new Date(NOW.getTime() - n * 86_400_000).toISOString();

  it("returns null for fewer than 3 points in window", () => {
    expect(ratePerWeek([], 7, NOW)).toBeNull();
    expect(ratePerWeek(
      [{ ts: dayAgo(1), value: 250 }, { ts: dayAgo(2), value: 251 }],
      7, NOW,
    )).toBeNull();
  });

  it("recovers a clean linear loss rate", () => {
    // Lose 1 lb/week for 4 weeks. Daily samples.
    const pts = Array.from({ length: 28 }, (_, i) => ({
      ts: dayAgo(27 - i),
      value: 250 - (i / 7),
    }));
    const r = ratePerWeek(pts, 28, NOW);
    expect(r).not.toBeNull();
    expect(r!).toBeCloseTo(-1, 2);
  });

  it("ignores points outside the window", () => {
    // Old points show a fast loss; recent week is flat. The 7d rate
    // should reflect only the recent week.
    const old = Array.from({ length: 14 }, (_, i) => ({
      ts: dayAgo(27 - i), value: 260 - i,
    }));
    const recent = Array.from({ length: 7 }, (_, i) => ({
      ts: dayAgo(6 - i), value: 250 + (i % 2) * 0.1,
    }));
    const r = ratePerWeek([...old, ...recent], 7, NOW);
    expect(r).not.toBeNull();
    expect(Math.abs(r!)).toBeLessThan(0.5);
  });

  it("positive value means gaining", () => {
    const pts = Array.from({ length: 14 }, (_, i) => ({
      ts: dayAgo(13 - i),
      value: 250 + (i / 7),
    }));
    const r = ratePerWeek(pts, 14, NOW);
    expect(r).not.toBeNull();
    expect(r!).toBeGreaterThan(0.5);
  });
});
