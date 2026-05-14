import type { Summary } from "../api/types";

/** Convert today's recovery snapshot to a single human sentence for
 *  the kiosk. Returns "—" if there's nothing usable yet. */
export function recoverySentence(summary: Summary | undefined): string {
  if (!summary) return "—";
  const parts: string[] = [];

  // Sleep
  if (summary.sleep?.duration_s) {
    const h = Math.round(summary.sleep.duration_s / 3600);
    parts.push(`Slept ${h}h`);
  }

  // HRV — qualitative: low (<35), normal (35-50), high (>50). Reference
  // ranges are user-specific; these thresholds match what the user has
  // been seeing in recent dashboards. Adjust later if needed.
  const hrv = summary.hrv?.rmssd_ms;
  let recovery: "low" | "normal" | "high" | null = null;
  if (hrv != null) {
    if (hrv < 35) recovery = "low";
    else if (hrv > 50) recovery = "high";
    else recovery = "normal";
  }

  // Closer
  if (recovery === "low") parts.push("recovery low — easy day");
  else if (recovery === "high") parts.push("recovery strong — go");
  else if (recovery === "normal") parts.push("recovery steady");

  return parts.length === 0 ? "—" : `${parts.join(", ")}.`;
}
