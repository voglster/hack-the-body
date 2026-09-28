import { describe, expect, it } from "vitest";

import { describeButton, mappingFor } from "./remoteButtons";

describe("remote button mapping", () => {
  it("a food button needs a food before it can save", () => {
    expect(mappingFor("r/right", { action: "food", oz: "16", food: null })).toBeNull();
    expect(mappingFor("r/right", { action: "food", oz: "16",
                                   food: { id: "f1", name: "Shake", quantity_g: 325 } }))
      .toEqual({ button: "r/right", action: "food", label: "Shake", food_id: "f1", quantity_g: 325 });
  });

  it("water falls back to a pint", () => {
    expect(mappingFor("r/up", { action: "water", oz: "", food: null })?.oz).toBe(16);
    expect(describeButton({ button: "r/up", action: "water", label: "Water", oz: 24 })).toBe("Water 24 oz");
  });
});
