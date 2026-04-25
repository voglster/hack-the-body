import type {
  Summary, WeightPoint, SleepPoint, HRVPoint, RHRPoint, VO2MaxPoint, DailySummaryPoint, Workout,
  Food, MealEntry, MealTemplate, MealSlot, TodayTotals, StepsToday, CoachInsight, CoachRecentEntry, SyncStatus, WaterToday, VitaminsToday,
} from "./types";
import { clearApiKey, getApiKey } from "../lib/auth";

declare global {
  interface Window { __HTB__?: { apiUrl?: string }; }
}

const BASE = window.__HTB__?.apiUrl ?? import.meta.env.VITE_API_URL ?? "";

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const key = getApiKey();
  return key ? { "X-API-Key": key, ...extra } : { ...extra };
}

/** If the server says 401, our cached key is stale (rotated or never valid).
 *  Clear it so the AuthGate re-prompts. Throw an error so callers know. */
function handleUnauthorized(): never {
  clearApiKey();
  throw new Error("unauthorized");
}

async function get<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { headers: authHeaders() });
  if (r.status === 401) handleUnauthorized();
  if (!r.ok) throw new Error(`GET ${path} failed: ${r.status}`);
  return (await r.json()) as T;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(body ?? {}),
  });
  if (r.status === 401) handleUnauthorized();
  if (!r.ok) throw new Error(`POST ${path} failed: ${r.status} ${await r.text().catch(() => "")}`);
  return (await r.json()) as T;
}

async function del(path: string): Promise<void> {
  const r = await fetch(`${BASE}${path}`, { method: "DELETE", headers: authHeaders() });
  if (r.status === 401) handleUnauthorized();
  if (!r.ok && r.status !== 204) throw new Error(`DELETE ${path} failed: ${r.status}`);
}

export const api = {
  summary: () => get<Summary>("/metrics/summary"),
  weightRange: (days = 60) => get<WeightPoint[]>(`/metrics/weight/range?days=${days}`),
  sleepRange:  (days = 30) => get<SleepPoint[]>(`/metrics/sleep/range?days=${days}`),
  hrvRange:    (days = 30) => get<HRVPoint[]>(`/metrics/hrv/range?days=${days}`),
  rhrRange:    (days = 30) => get<RHRPoint[]>(`/metrics/rhr/range?days=${days}`),
  vo2maxRange: (days = 90) => get<VO2MaxPoint[]>(`/metrics/vo2max/range?days=${days}`),
  stepsRange:  (days = 30) => get<DailySummaryPoint[]>(`/metrics/daily_summary/range?days=${days}`),
  stepsDay: (start: string, end: string) =>
    get<StepsToday>(
      `/metrics/steps/day?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
    ),
  workouts:    (days = 14) => get<Workout[]>(`/workouts?days=${days}`),
  triggerIngest: async (source: string): Promise<unknown> => {
    const r = await fetch(`${BASE}/admin/ingest/${source}`, {
      method: "POST", headers: authHeaders(),
    });
    if (r.status === 401) handleUnauthorized();
    if (!r.ok) throw new Error(`trigger failed: ${r.status}`);
    return (await r.json()) as unknown;
  },

  // foods
  searchFoods: (q: string, limit = 20) =>
    get<Food[]>(`/foods/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  foodByBarcode: (barcode: string) =>
    get<Food>(`/foods/barcode/${encodeURIComponent(barcode)}`),
  createFood: (food: Partial<Food>) => post<Food>("/foods", food),

  // meal entries
  todayTotals: () => get<TodayTotals>("/meals/today/totals"),
  todayEntries: () => get<MealEntry[]>("/meals/entries"),
  logEntry: (req: { food_id: string; quantity_g: number; slot: MealSlot; note?: string }) =>
    post<MealEntry>("/meals/entries", req),
  deleteEntry: (entry_id: string) => del(`/meals/entries/${entry_id}`),
  editEntry: (entry_id: string, patch: { ts?: string; slot?: MealSlot }) => {
    return fetch(`${BASE}/meals/entries/${entry_id}`, {
      method: "PATCH",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(patch),
    }).then(async r => {
      if (r.status === 401) handleUnauthorized();
      if (!r.ok) throw new Error(`PATCH failed: ${r.status} ${await r.text().catch(() => "")}`);
      return (await r.json()) as MealEntry;
    });
  },

  // coach
  coachInsight: () => get<CoachInsight>("/coach/insight"),
  coachRecent: (limit = 10) => get<CoachRecentEntry[]>(`/coach/recent?limit=${limit}`),
  coachWeekly: () => get<CoachInsight>("/coach/weekly"),

  // admin
  syncStatus: () => get<SyncStatus>("/admin/sync-status"),

  // water
  waterToday: () => get<WaterToday>("/water/today"),
  logWater: (oz: number) => post<MealEntry>("/water/log", { oz }),

  // vitamins
  vitaminsToday: () => get<VitaminsToday>("/vitamins/today"),
  logVitamins: () => post<MealEntry>("/vitamins/log", {}),

  // push
  vapidPublicKey: () => get<{ public_key: string }>("/push/vapid-public-key"),
  pushSubscribe: (sub: PushSubscriptionJSON) => post<unknown>("/push/subscribe", sub),
  pushUnsubscribe: (endpoint: string) =>
    del(`/push/subscribe?endpoint=${encodeURIComponent(endpoint)}`),
  pushTest: () => post<{ sent: number; pruned: number; failed: number; subscriptions: number }>(
    "/push/test", {},
  ),

  // templates
  listTemplates: () => get<MealTemplate[]>("/meals/templates"),
  createTemplate: (t: Partial<MealTemplate>) => post<MealTemplate>("/meals/templates", t),
  logTemplate: (template_id: string, slot?: MealSlot) =>
    post<{ template: string; entries: MealEntry[] }>(`/meals/templates/${template_id}/log`, slot ? { slot } : {}),
  deleteTemplate: (template_id: string) => del(`/meals/templates/${template_id}`),
};
