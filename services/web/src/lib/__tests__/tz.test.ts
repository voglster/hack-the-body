import { describe, expect, it } from "vitest";

import { localDayBoundsUTC, shiftLocalISO, todayLocalISO } from "../tz";

describe("tz helpers", () => {
  it("localDayBoundsUTC produces a 24-hour window", () => {
    const { start, end } = localDayBoundsUTC("2026-04-25");
    const ms = new Date(end).getTime() - new Date(start).getTime();
    expect(ms).toBe(24 * 60 * 60 * 1000);
  });

  it("shiftLocalISO walks days forward and back", () => {
    expect(shiftLocalISO("2026-04-25", 1)).toBe("2026-04-26");
    expect(shiftLocalISO("2026-04-25", -7)).toBe("2026-04-18");
    // Crosses month boundary.
    expect(shiftLocalISO("2026-04-30", 1)).toBe("2026-05-01");
  });

  it("todayLocalISO matches YYYY-MM-DD format", () => {
    expect(todayLocalISO()).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});
