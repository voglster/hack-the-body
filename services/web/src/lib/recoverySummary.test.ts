import { describe, expect, it } from "vitest";

import { recoverySentence } from "./recoverySummary";
import type { Summary } from "../api/types";

describe("recoverySentence", () => {
  it("returns dash when summary is undefined", () => {
    expect(recoverySentence(undefined)).toBe("—");
  });
  it("describes sleep alone when HRV missing", () => {
    const s = { sleep: { duration_s: 27000 } } as Summary;
    expect(recoverySentence(s)).toBe("Slept 8h.");
  });
  it("flags low HRV", () => {
    const s = { sleep: { duration_s: 21600 }, hrv: { rmssd_ms: 30 } } as Summary;
    expect(recoverySentence(s)).toBe("Slept 6h, recovery low — easy day.");
  });
  it("flags high HRV", () => {
    const s = { sleep: { duration_s: 28800 }, hrv: { rmssd_ms: 60 } } as Summary;
    expect(recoverySentence(s)).toBe("Slept 8h, recovery strong — go.");
  });
  it("steady when HRV is in normal band", () => {
    const s = { sleep: { duration_s: 25200 }, hrv: { rmssd_ms: 42 } } as Summary;
    expect(recoverySentence(s)).toBe("Slept 7h, recovery steady.");
  });
});
