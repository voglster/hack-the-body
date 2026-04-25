import type {
  Summary, WeightPoint, SleepPoint, HRVPoint, RHRPoint, VO2MaxPoint, DailySummaryPoint, Workout,
} from "./types";

declare global {
  interface Window { __HTB__?: { apiUrl?: string; apiKey?: string }; }
}

const BASE = window.__HTB__?.apiUrl ?? import.meta.env.VITE_API_URL ?? "";
const KEY = window.__HTB__?.apiKey ?? import.meta.env.VITE_API_KEY ?? "";

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { headers: { "X-API-Key": KEY } });
  if (!r.ok) throw new Error(`GET ${path} failed: ${r.status}`);
  return (await r.json()) as T;
}

export const api = {
  summary: () => get<Summary>("/metrics/summary"),
  weightRange: (days = 60) => get<WeightPoint[]>(`/metrics/weight/range?days=${days}`),
  sleepRange:  (days = 30) => get<SleepPoint[]>(`/metrics/sleep/range?days=${days}`),
  hrvRange:    (days = 30) => get<HRVPoint[]>(`/metrics/hrv/range?days=${days}`),
  rhrRange:    (days = 30) => get<RHRPoint[]>(`/metrics/rhr/range?days=${days}`),
  vo2maxRange: (days = 90) => get<VO2MaxPoint[]>(`/metrics/vo2max/range?days=${days}`),
  stepsRange:  (days = 30) => get<DailySummaryPoint[]>(`/metrics/daily_summary/range?days=${days}`),
  workouts:    (days = 14) => get<Workout[]>(`/workouts?days=${days}`),
  triggerIngest: async (source: string) => {
    const r = await fetch(`${BASE}/admin/ingest/${source}`, {
      method: "POST",
      headers: { "X-API-Key": KEY },
    });
    if (!r.ok) throw new Error(`trigger failed: ${r.status}`);
    return r.json();
  },
};
