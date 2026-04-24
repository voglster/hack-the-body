import { describe, expect, it } from "vitest";
import { rollingAverage } from "../trend";

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
