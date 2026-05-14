import { useEffect, useState } from "react";

import { KioskChecklist } from "../components/kiosk/KioskChecklist";
import { KioskCoachLine } from "../components/kiosk/KioskCoachLine";
import { KioskRecoveryStrip } from "../components/kiosk/KioskRecoveryStrip";
import { KioskStepsHero } from "../components/kiosk/KioskStepsHero";

function useClock() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(id);
  }, []);
  return now;
}

export function Kiosk() {
  const now = useClock();
  const time = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const date = now.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });

  return (
    <div className="min-h-screen bg-black text-white p-8 flex flex-col gap-6 font-sans">
      <header className="flex items-baseline justify-between">
        <div className="flex items-baseline gap-6">
          <div className="text-5xl font-semibold tabular-nums">{time}</div>
          <div className="text-xl text-neutral-400">{date}</div>
        </div>
        <div className="text-xs text-neutral-500 uppercase tracking-widest">
          Hack the Body
        </div>
      </header>

      <KioskCoachLine />

      <main className="grid grid-cols-2 gap-6 flex-1">
        <KioskStepsHero />
        <KioskChecklist />
      </main>

      <KioskRecoveryStrip />
    </div>
  );
}
