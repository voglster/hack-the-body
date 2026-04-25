export interface Summary {
  weight: WeightPoint | null;
  sleep: SleepPoint | null;
  hrv: HRVPoint | null;
  rhr: RHRPoint | null;
  body_comp: BodyCompPoint | null;
  vo2max: VO2MaxPoint | null;
  daily_summary: DailySummaryPoint | null;
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
