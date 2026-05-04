export interface Point { ts: string; value: number; }
export interface Averaged extends Point { avg: number; }

export function rollingAverage(pts: Point[], window: number): Averaged[] {
  const out: Averaged[] = [];
  for (let i = 0; i < pts.length; i++) {
    const start = Math.max(0, i - window + 1);
    const slice = pts.slice(start, i + 1);
    const avg = slice.reduce((s, p) => s + p.value, 0) / slice.length;
    out.push({ ...pts[i], avg });
  }
  return out;
}

const MS_PER_DAY = 86_400_000;
const MS_PER_WEEK = 7 * MS_PER_DAY;

// Least-squares slope of `pts` over the last `days` window, expressed as
// units-per-week (so for weight in lb, the return is lb/week — positive
// = gaining, negative = losing). Returns null if there are fewer than
// 3 points in the window. Robust to noise; cleaner than endpoint-diff.
export function ratePerWeek(pts: Point[], days: number, now?: Date): number | null {
  if (pts.length < 3) return null;
  const nowMs = (now ?? new Date()).getTime();
  const cutoff = nowMs - days * MS_PER_DAY;
  const slice = pts
    .map(p => ({ x: new Date(p.ts).getTime(), y: p.value }))
    .filter(p => p.x >= cutoff && Number.isFinite(p.x) && Number.isFinite(p.y));
  if (slice.length < 3) return null;
  const n = slice.length;
  const meanX = slice.reduce((s, p) => s + p.x, 0) / n;
  const meanY = slice.reduce((s, p) => s + p.y, 0) / n;
  let num = 0;
  let den = 0;
  for (const p of slice) {
    num += (p.x - meanX) * (p.y - meanY);
    den += (p.x - meanX) ** 2;
  }
  if (den === 0) return null;
  // num/den is units-per-ms. Convert to per-week.
  return (num / den) * MS_PER_WEEK;
}
