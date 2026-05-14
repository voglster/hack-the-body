/** Bank of short tagline quotes shown at the bottom of the kiosk.
 *  Rotates once per day (deterministic by day-of-year), stable within
 *  the day. Mix of dry observational, philosophical, and stoic — never
 *  precious, never two exclamation marks, never "you got this." */

export const QUOTES = [
  "The body is a project with no deadline and no days off.",
  "Discipline is choosing between what you want now and what you want most.",
  "Small things, often.",
  "Sweat is just fat crying. Also water.",
  "The dose makes the poison; the habit makes the man.",
  "Show up. The rest is negotiable.",
  "Motion is the cure for almost everything.",
  "You don't rise to your goals. You fall to your systems.",
  "Easy day, still a day.",
  "The work doesn't care how you feel about it.",
  "Volume is a vote. Cast yours.",
  "Tomorrow's body is built tonight.",
  "Adaptation is the entire game.",
  "Slow is smooth. Smooth is fast.",
  "The cost is the cost. The benefit compounds.",
  "Sleep is the steroid you already paid for.",
  "Protein, water, walk. Repeat indefinitely.",
  "The strongest people make time, not excuses.",
  "Today's effort is tomorrow's baseline.",
  "Boring is sustainable. Sustainable is rare.",
  "Hard work beats talent, when talent doesn't work hard.",
  "Consistency turns minutes into years.",
  "Recovery is training. Skipping it isn't toughness.",
  "Decide once, execute daily.",
  "Less variety, more frequency.",
  "Form before load. Load before speed.",
  "The journey of a thousand miles begins with a single step. Take it.",
  "Strong people are harder to kill, and more useful in general.",
  "A walk is never wasted.",
  "Earn your evening.",
];

/** Day-of-year (0-based) for the local date in `now`. */
function dayOfYear(now: Date): number {
  const start = new Date(now.getFullYear(), 0, 0);
  const diff = now.getTime() - start.getTime();
  return Math.floor(diff / 86_400_000);
}

export function dailyQuote(now: Date = new Date()): string {
  const idx = dayOfYear(now) % QUOTES.length;
  return QUOTES[idx];
}
