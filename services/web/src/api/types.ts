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
  // Optional, populated for Hevy strength rows; absent for cardio.
  title?: string | null;
  exercise_count?: number | null;
  set_count?: number | null;
  updated_at?: string | null;
}

export interface StrengthSetView {
  set_index: number;
  set_type: string | null;
  reps: number | null;
  weight_kg: number | null;
  distance_m: number | null;
  duration_s: number | null;
  rpe: number | null;
}

export interface WorkoutDetailExercise {
  index: number;
  title: string;
  template_id: string | null;
  notes: string | null;
  superset_id: string | null;
  sets: StrengthSetView[];
}

export interface WorkoutDetail extends Workout {
  exercises?: WorkoutDetailExercise[];
}

/** Live treadmill session, computed from raw `treadmill_samples`.
 *  /workouts/active returns 204 when nothing is active. */
export interface ActiveWorkout {
  status: "active" | "complete";
  started_at: string;
  ended_at: string;
  duration_s: number;
  active_s: number;
  distance_mi: number;
  distance_m: number;
  avg_speed_mph: number;
  max_speed_mph: number;
  avg_grade_pct: number;
  max_grade_pct: number;
  avg_hr: number | null;
  max_hr: number | null;
  hr_zones_s: { z1: number; z2: number; z3: number; z4: number; z5: number };
  calories: number;
  sample_count: number;
  /** Last ~2.5s window. Null when status is "complete" (would be stale)
   *  or when no recent samples carry the field. */
  current_speed_mph: number | null;
  current_grade_pct: number | null;
  current_hr: number | null;
  source: string;
  source_id: string;
  activity_type: string;
}

export interface TreadmillSample {
  ts: string;
  source: string;
  state: number;
  speed_mph: number | null;
  grade_pct: number | null;
  distance_raw: number | null;
  calories: number | null;
  twork_s: number | null;
  hr_bpm: number | null;
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

export interface UsualSuggestion {
  name: string;
  slot: MealSlot;
  items: MealTemplateItem[];
  rationale: string;
  signature: string;
}

export interface UsualSuggestionsResponse {
  suggestions: UsualSuggestion[];
  generated_at: string;
  error?: string;
}

export interface SyncStatusEntry {
  last_ok: { source: string; status: string; started_at: string; finished_at: string | null;
             counts: Record<string, number>; error: string | null } | null;
  last_error: { source: string; status: string; started_at: string; finished_at: string | null;
                counts: Record<string, number>; error: string | null } | null;
}
export type SyncStatus = Record<string, SyncStatusEntry>;

export interface CoachFoodTotals {
  calories?: number;
  protein_g?: number;
  carbs_g?: number;
  fat_g?: number;
  entries?: number;
  food_logged_today?: boolean;
  water_oz?: number;
}

export interface CoachToolCall {
  name: string;
  args: Record<string, unknown>;
  result: Record<string, unknown>;
}

export interface CoachTurn {
  role: "coach" | "user";
  text: string;
  ts: string;
  tool_calls?: CoachToolCall[] | null;
  findings_snapshot?: Record<string, unknown> | null;
}

export interface CoachThread {
  id: string;
  started_at: string;
  last_activity_at: string;
  surface: string;
  turns: CoachTurn[];
}

export interface CoachReplyRequest {
  text: string;
}

export interface CoachInsight {
  id: string | null;
  text: string;
  model: string;
  eval_ms: number;
  total_ms: number;
  generated_at: string;
  context: Record<string, unknown>;
  trigger: string;
  food_totals?: CoachFoodTotals | null;
  thread_id?: string | null;
}

export type KioskUrgency = "clear" | "action" | "urgent";

export interface KioskGlance extends CoachInsight {
  verb: string;
  qualifier: string;
  urgency: KioskUrgency;
  coach: string;
}

export interface CoachRecentEntry {
  id: string;
  text: string;
  generated_at: string;
  trigger: string;
  food_totals?: CoachFoodTotals | null;
  context?: Record<string, unknown> | null;
}

export interface UserTargets {
  daily_calories: number | null;
  daily_protein_g: number | null;
  daily_fat_g: number | null;
  daily_carbs_g: number | null;
  daily_water_oz: number | null;
  step_goal_override: number | null;
  goal_weight_lb: number | null;
  weekly_loss_rate_min_lb: number | null;
  weekly_loss_rate_max_lb: number | null;
  updated_at?: string;
}

/** Ephemeral "what's the coach should know about today" note. Resets
 *  at local midnight via the server-computed `is_today` flag — when
 *  false, the stored note is yesterday's and `text` is returned empty. */
export interface DayNote {
  text: string;
  local_date: string | null;
  is_today: boolean;
  set_at: string | null;
}

/** Long-lived stance / goals the coach reads on every generation. */
export interface CoachNote {
  text: string;
  updated_at: string | null;
}

export type CoachFeedbackRating = "up" | "down";

export interface CoachFeedback {
  id: string;
  insight_id: string;
  rating: CoachFeedbackRating;
  note: string | null;
  created_at: string;
}

export type NudgeSeverity = "info" | "warn";

export interface FiredNudge {
  id: string;
  kind: string;
  severity: NudgeSeverity;
  title: string;
  body: string;
  dismissable: boolean;
}

export interface NudgesResponse {
  nudges: FiredNudge[];
  generated_at: string;
}

export interface DismissNudgeReq {
  nudge_id: string;
  until: "end_of_day" | string;
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

// ---------- habits ----------

export type HabitKind = "auto" | "manual" | "none";
export type HabitStatusValue = "done" | "skipped" | "missed" | "unknown";

export interface Habit {
  id: string;
  name: string;
  kind: HabitKind;
  resolver?: string | null;
  active: boolean;
  created_at?: string;
}

export interface HabitStatusToday {
  id: string;
  name: string;
  kind: HabitKind;
  resolver?: string | null;
  status: HabitStatusValue;
  source: "auto" | "manual" | "coach" | "none";
}

export interface CreateHabitRequest {
  name: string;
  kind: HabitKind;
  resolver?: string;
}
