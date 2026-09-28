import { describe, expect, it } from "vitest";

import { cumulative, paceAt, verdict } from "./stepsPace";

describe("even pace", () => {
  it("spreads the goal evenly from 7am to lights-out", () => {
    expect(paceAt(7, 12000, 22)).toBe(0);
    expect(paceAt(14.5, 12000, 22)).toBe(6000);
    expect(paceAt(23, 12000, 22)).toBe(12000);
  });

  it("calls 2:30pm at 4,000 of 12k behind, with the hourly ask to finish", () => {
    const v = verdict(4000, 14.5, 14.5, 12000, 22);
    expect(v.status).toBe("behind");
    expect(v.headline).toBe("Behind by 2,000");
    expect(v.needPerHour).toBe(1067);
  });

  it("a small gap is on pace, a surplus is ahead, the goal is done", () => {
    expect(verdict(5800, 14.5, 14.5, 12000, 22).status).toBe("on-pace");
    expect(verdict(8000, 14.5, 14.5, 12000, 22).headline).toBe("Ahead by 2,000");
    expect(verdict(12500, 18, 18, 12000, 22).status).toBe("done");
  });

  it("builds a running total in bucket order", () => {
    const b = (end: string, steps: number) => ({ ts: end, end_ts: end, steps, activity_level: null });
    const pts = cumulative([b("2026-09-28T09:15:00", 300), b("2026-09-28T09:00:00", 200)]);
    expect(pts.map((p) => p.steps)).toEqual([200, 500]);
    expect(pts[1].hour).toBe(9.25);
  });
});
