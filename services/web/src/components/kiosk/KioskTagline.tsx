import { dailyQuote } from "../../lib/quotes";

/** Daily-rotating short quote pinned at the bottom of the kiosk. */
export function KioskTagline() {
  return (
    <footer className="text-xl text-neutral-600 italic leading-relaxed">
      {dailyQuote()}
    </footer>
  );
}
