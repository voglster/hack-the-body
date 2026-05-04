import { describe, expect, it } from "vitest";

import { localDayBoundsUTC, shiftLocalISO, slotTimestampUTC, todayLocalISO } from "../tz";

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

  it("slotTimestampUTC pins to slot-typical local hour on the given day", () => {
    // Round-trip via local Date so the test is timezone-agnostic.
    const dinner = new Date(slotTimestampUTC("2026-04-25", "dinner"));
    expect(dinner.getFullYear()).toBe(2026);
    expect(dinner.getMonth()).toBe(3);
    expect(dinner.getDate()).toBe(25);
    expect(dinner.getHours()).toBe(19);

    const breakfast = new Date(slotTimestampUTC("2026-04-25", "breakfast"));
    expect(breakfast.getHours()).toBe(8);

    // Unknown slot falls back to noon.
    const unknown = new Date(slotTimestampUTC("2026-04-25", "lateNight"));
    expect(unknown.getHours()).toBe(12);
  });
});
