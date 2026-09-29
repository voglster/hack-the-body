import type { RecentActivity } from "../api/types";

export type Tone = "done" | "undone" | "waiting" | "needs-you";

export interface ActivityLine { icon: string; text: string; tone: Tone }

const SOURCE: Partial<Record<NonNullable<RecentActivity["source"]>, string>> = {
  button: "remote", voice: "voice",
};

export function describeActivity(a: RecentActivity): ActivityLine {
  const via = a.source && SOURCE[a.source] ? ` · ${SOURCE[a.source]}` : "";
  switch (a.kind) {
    case "undone":
      return { icon: "↶", text: `Undid ${a.label}${via}`, tone: "undone" };
    case "pending":
      return { icon: "…", text: `Working on “${a.label}”`, tone: "waiting" };
    case "needs_confirm":
      return { icon: "?", text: `“${a.label}” — pick which on your phone`, tone: "needs-you" };
    case "placeholder":
      return { icon: "🍽", text: `Ate something — fill it in later${via}`, tone: "needs-you" };
    case "failed":
      return { icon: "!", text: `Couldn't work out “${a.label}”`, tone: "needs-you" };
    default:
      if (a.water_oz) return { icon: "💧", text: `Water +${a.water_oz} oz${via}`, tone: "done" };
      return { icon: "✓", text: `${a.label}${a.kcal ? `, ${a.kcal.toLocaleString()} kcal` : ""}${via}`, tone: "done" };
  }
}
