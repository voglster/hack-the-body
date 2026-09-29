import { describe, expect, it } from "vitest";

import type { RecentActivity } from "../api/types";
import { describeActivity } from "./recentActivity";

const a = (over: Partial<RecentActivity>): RecentActivity => ({
  at: "2026-09-29T18:00:00Z", kind: "logged", label: "Protein Bar", source: "button",
  kcal: 200, water_oz: null, ...over,
});

describe("describeActivity", () => {
  it("says what a remote press logged", () => {
    expect(describeActivity(a({}))).toEqual({ icon: "✓", text: "Protein Bar, 200 kcal · remote", tone: "done" });
  });
  it("water reads as ounces, undo as undo", () => {
    expect(describeActivity(a({ label: "Water", kcal: null, water_oz: 16 })).text).toBe("Water +16 oz · remote");
    expect(describeActivity(a({ kind: "undone" })).text).toBe("Undid Protein Bar · remote");
  });
  it("typed captures in progress show the words", () => {
    expect(describeActivity(a({ kind: "pending", label: "burger and fries", source: "text" })).text)
      .toBe("Working on “burger and fries”");
  });
});
