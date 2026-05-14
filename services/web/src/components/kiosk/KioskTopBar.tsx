import { useEffect, useState } from "react";

/** Thin top bar: brand left, date + time right, with a hairline
 *  "waking day" progress strip beneath. The strip fills the fraction
 *  of the 5am–11pm window that has elapsed. Quiet visual clock. */
export function KioskTopBar() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(id);
  }, []);

  const time = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const date = now.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });

  const wakingStart = 5;
  const wakingEnd = 23;
  const hours = now.getHours() + now.getMinutes() / 60;
  const frac = Math.min(1, Math.max(0, (hours - wakingStart) / (wakingEnd - wakingStart)));
  const pct = Math.round(frac * 100);

  return (
    <header className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between text-xl text-neutral-500 uppercase tracking-widest">
        <span>Hack the Body</span>
        <span className="tabular-nums">{date} · {time}</span>
      </div>
      <div className="h-1 bg-neutral-900 overflow-hidden">
        <div className="h-full bg-neutral-700" style={{ width: `${pct}%` }} />
      </div>
    </header>
  );
}
