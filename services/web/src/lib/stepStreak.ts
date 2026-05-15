import type { DailySummaryPoint } from "../api/types";

/** Step-goal streak with "never miss twice" forgiveness.
 *
 *  Rule: a day is a "hit" if steps >= step_goal. Streaks track
 *  consecutive hits, but a single miss between two hits is forgiven
 *  (the streak survives). Two consecutive misses ends the streak.
 *
 *  current_streak is anchored at the most recent day in the input
 *  (assumed to be "today"). If today is a miss but yesterday is a
 *  hit, today is treated as in-progress: the streak number from
 *  yesterday is shown, and breaks only if tomorrow is also a miss.
 */

export interface StreakResult {
  current: number;
  longest: number;
}

function isHit(d: DailySummaryPoint): boolean {
  return !!d.step_goal && d.steps >= d.step_goal;
}

export function stepStreak(history: DailySummaryPoint[]): StreakResult {
  if (history.length === 0) return { current: 0, longest: 0 };

  // Sort ascending by date so we walk chronologically.
  const sorted = [...history].sort((a, b) => (a.ts < b.ts ? -1 : 1));

  let longest = 0;
  let run = 0;
  let prevMissed = false;

  for (const d of sorted) {
    if (isHit(d)) {
      run += 1;
      prevMissed = false;
      if (run > longest) longest = run;
    } else if (!prevMissed) {
      // First miss — streak survives, day doesn't count toward run.
      prevMissed = true;
    } else {
      // Second consecutive miss — streak ends.
      run = 0;
      prevMissed = false;
    }
  }

  return { current: run, longest };
}
