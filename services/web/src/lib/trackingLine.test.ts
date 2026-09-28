import { describe, expect, it } from "vitest";

import { trackingLine } from "./trackingLine";

describe("trackingLine", () => {
  it("contrasts logged and unlogged weeks", () => {
    expect(trackingLine({ tracked_lb_per_week: -1.8, tracked_weeks: 5,
                          untracked_lb_per_week: 0.9, untracked_weeks: 8 }))
      .toBe("Weeks you log: -1.8 lb/wk. Weeks you don't: +0.9 lb/wk.");
  });

  it("stays quiet without both kinds of week", () => {
    expect(trackingLine({ tracked_lb_per_week: null, tracked_weeks: 0,
                          untracked_lb_per_week: 0.9, untracked_weeks: 8 })).toBeNull();
  });
});
