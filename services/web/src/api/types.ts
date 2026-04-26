export interface Summary {
  weight: WeightPoint | null;
  sleep: SleepPoint | null;
  hrv: HRVPoint | null;
  rhr: RHRPoint | null;
  body_comp: BodyCompPoint | null;
  vo2max: VO2MaxPoint | null;
  daily_summary: DailySummaryPoint | null;
}

export interface StepsBucket {
  ts: string;
  end_ts: string;
  steps: number;
  activity_level: string | null;
}

export interface StepsToday {
  total: number;
  buckets: StepsBucket[];
  as_of: string;
}

export interface DailySummaryPoint {
  ts: string;
  steps: number;
  step_goal: number | null;
  distance_m: number | null;
  active_kcal: number | null;
  total_kcal: number | null;
  resting_hr: number | null;
  intensity_minutes: number | null;
  floors_climbed: number | null;
  meta?: Meta;
}

export interface WeightPoint { ts: string; kg: number; meta?: Meta; }
export interface SleepPoint {
  ts: string; duration_s: number; deep_s: number; rem_s: number;
  light_s: number; awake_s: number; score: number | null; meta?: Meta;
}
export interface HRVPoint { ts: string; rmssd_ms: number; meta?: Meta; }
export interface RHRPoint { ts: string; bpm: number; meta?: Meta; }
export interface BodyCompPoint {
  ts: string; weight_kg: number;
  body_fat_pct: number | null; muscle_mass_kg: number | null;
  body_water_pct: number | null; bone_mass_kg: number | null;
  meta?: Meta;
}
export interface VO2MaxPoint { ts: string; value: number; meta?: Meta; }
export interface Workout {
  ts: string; activity_type: string; duration_s: number;
  distance_m: number | null; avg_hr: number | null; max_hr: number | null;
  calories: number | null; notes: string | null;
  source: string; source_id: string;
}
interface Meta { source: string; source_id: string; }

export interface WaterToday {
  oz: number;
  ml: number;
  entries: number;
  start: string;
  end: string;
}

// ---------- food / meals ----------

export type MealSlot = "breakfast" | "lunch" | "dinner" | "snack" | "supplement";
export type FoodCategory = "food" | "supplement" | "drink";

export interface ParsedFoodItem {
  name: string;
  servings: number;
  calories: number | null;
  protein_g: number | null;
  carbs_g: number | null;
  fat_g: number | null;
}

export interface VitaminsToday {
  logged: boolean;
  entries: number;
  first_ts: string | null;
  start: string;
  end: string;
}

export interface Macros {
  calories: number | null;
  protein_g: number | null;
  carbs_g: number | null;
  fat_g: number | null;
  fiber_g: number | null;
  sugar_g: number | null;
  sodium_mg: number | null;
}

export interface Food {
  id: string;
  name: string;
  brand: string | null;
  barcode: string | null;
  category: FoodCategory;
  serving_g: number;
  serving_label: string | null;
  per_serving: Partial<Macros>;
  source: string;
}

export interface MealEntry {
  id: string;
  ts: string;
  food_id: string;
  food_name: string;
  food_category: FoodCategory;
  quantity_g: number;
  servings: number | null;
  slot: MealSlot;
  template_id: string | null;
  note: string | null;
  macros: Partial<Macros>;
}

export interface MealTemplateItem {
  food_id: string;
  quantity_g: number;
}

export interface MealTemplate {
  id: string;
  name: string;
  description: string | null;
  default_slot: MealSlot;
  items: MealTemplateItem[];
}

export interface SyncStatusEntry {
  last_ok: { source: string; status: string; started_at: string; finished_at: string | null;
             counts: Record<string, number>; error: string | null } | null;
  last_error: { source: string; status: string; started_at: string; finished_at: string | null;
                counts: Record<string, number>; error: string | null } | null;
}
export type SyncStatus = Record<string, SyncStatusEntry>;

export interface CoachInsight {
  text: string;
  model: string;
  eval_ms: number;
  total_ms: number;
  generated_at: string;
  context: Record<string, unknown>;
  trigger: string;
}

export interface CoachRecentEntry {
  text: string;
  generated_at: string;
  trigger: string;
}

export interface TodayTotals {
  totals: {
    calories: number; protein_g: number; carbs_g: number; fat_g: number;
    fiber_g: number; sugar_g: number; sodium_mg: number;
  };
  by_slot: Record<MealSlot, { calories: number; protein_g: number; carbs_g: number; fat_g: number }>;
  supplements: { id: string; name: string; ts: string; quantity_g: number }[];
  entry_count: number;
}
