import { describe, expect, it } from "vitest";

import { QUOTES, dailyQuote } from "./quotes";

describe("dailyQuote", () => {
  it("returns a quote from the bank", () => {
    expect(QUOTES).toContain(dailyQuote(new Date(2026, 0, 1)));
  });
  it("is stable across the same day", () => {
    const a = dailyQuote(new Date(2026, 4, 14, 7, 0));
    const b = dailyQuote(new Date(2026, 4, 14, 23, 59));
    expect(a).toBe(b);
  });
  it("changes across days", () => {
    const a = dailyQuote(new Date(2026, 4, 14));
    const b = dailyQuote(new Date(2026, 4, 15));
    expect(a).not.toBe(b);
  });
});
