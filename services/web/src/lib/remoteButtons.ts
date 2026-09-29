import type { ButtonAction, RemoteButton } from "../api/types";

export const DEFAULT_WATER_OZ = 16;

export const ACTION_LABEL: Record<ButtonAction, string> = {
  food: "Log a food", usual: "A usual", water: "Water", habit: "Vitamins", placeholder: "I just ate", undo: "Undo",
};

export function describeButton(b: RemoteButton | undefined): string {
  if (!b) return "not set";
  if (b.action === "water") return `Water ${b.oz ?? DEFAULT_WATER_OZ} oz`;
  return b.label;
}

export interface Draft {
  action: ButtonAction;
  oz: string;
  food: { id: string; name: string; quantity_g: number } | null;
  usual?: { id: string; name: string } | null;
}

/** The mapping a draft saves as, or null when it isn't complete yet (a food action with no food). */
export function mappingFor(button: string, d: Draft): RemoteButton | null {
  switch (d.action) {
    case "food":
      return d.food
        ? { button, action: "food", label: d.food.name, food_id: d.food.id, quantity_g: d.food.quantity_g }
        : null;
    case "usual":
      return d.usual ? { button, action: "usual", label: d.usual.name, template_id: d.usual.id } : null;
    case "water":
      return { button, action: "water", label: "Water", oz: Number(d.oz) || DEFAULT_WATER_OZ };
    case "habit":
      return { button, action: "habit", label: "Vitamins", habit: "Vitamins" };
    default:
      return { button, action: d.action, label: ACTION_LABEL[d.action] };
  }
}

/** The editor's starting state for a button as it's mapped today. */
export function draftFrom(b: RemoteButton | undefined): Draft {
  return {
    action: b?.action ?? "food",
    oz: String(b?.oz ?? DEFAULT_WATER_OZ),
    food: b?.action === "food" && b.food_id
      ? { id: b.food_id, name: b.label, quantity_g: b.quantity_g ?? 100 } : null,
    usual: b?.action === "usual" && b.template_id ? { id: b.template_id, name: b.label } : null,
  };
}
