/**
 * Local-day windows for time-series queries.
 *
 * The Mongo records are stored in UTC. The browser knows the user's timezone.
 * Compute the local midnight-to-midnight window in UTC ISO strings so the API
 * doesn't need to know about timezones at all.
 */

export function localDayBoundsUTC(localDateISO: string): { start: string; end: string } {
  // localDateISO is "YYYY-MM-DD" interpreted in the browser's local timezone.
  const [y, m, d] = localDateISO.split("-").map(Number);
  const startLocal = new Date(y, m - 1, d, 0, 0, 0, 0);
  const endLocal = new Date(y, m - 1, d + 1, 0, 0, 0, 0);
  return { start: startLocal.toISOString(), end: endLocal.toISOString() };
}

export function todayLocalISO(): string {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function shiftLocalISO(localDateISO: string, delta: number): string {
  const [y, m, d] = localDateISO.split("-").map(Number);
  const dt = new Date(y, m - 1, d + delta);
  const yy = dt.getFullYear();
  const mm = String(dt.getMonth() + 1).padStart(2, "0");
  const dd = String(dt.getDate()).padStart(2, "0");
  return `${yy}-${mm}-${dd}`;
}

// Slot-typical local hour. When the user logs a forgotten meal to a past
// day we need *some* timestamp; rather than guess "midnight" or "now",
// pin to a sensible mealtime so the coach's time-of-day reasoning still
// works.
const SLOT_HOURS: Record<string, number> = {
  breakfast: 8,
  lunch: 12,
  dinner: 19,
  snack: 15,
  supplement: 9,
};

export function slotTimestampUTC(localDateISO: string, slot: string): string {
  const [y, m, d] = localDateISO.split("-").map(Number);
  const hour = SLOT_HOURS[slot] ?? 12;
  return new Date(y, m - 1, d, hour, 0, 0, 0).toISOString();
}

export function formatLocalDay(localDateISO: string): string {
  const [y, m, d] = localDateISO.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    weekday: "short", month: "short", day: "numeric",
  });
}
