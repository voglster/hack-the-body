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
