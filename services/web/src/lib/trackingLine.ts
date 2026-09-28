import type { LoggingStatus } from "../api/types";

function signed(lb: number): string {
  return `${lb > 0 ? "+" : ""}${lb.toFixed(1)} lb/wk`;
}

export function trackingLine(w: LoggingStatus["weight_by_tracking"]): string | null {
  if (w.tracked_lb_per_week == null || w.untracked_lb_per_week == null) return null;
  return `Weeks you log: ${signed(w.tracked_lb_per_week)}. Weeks you don't: ${signed(w.untracked_lb_per_week)}.`;
}
