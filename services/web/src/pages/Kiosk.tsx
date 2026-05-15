import { useEffect, useState } from "react";

import { KioskCoachLine } from "../components/kiosk/KioskCoachLine";
import { KioskHero } from "../components/kiosk/KioskHero";
import { KioskOpenList } from "../components/kiosk/KioskOpenList";
import { KioskRecoverySentence } from "../components/kiosk/KioskRecoverySentence";
import { KioskTagline } from "../components/kiosk/KioskTagline";
import { KioskTopBar } from "../components/kiosk/KioskTopBar";
import { phaseInfo } from "../lib/dayPhase";

export function Kiosk() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);
  const { windDownMode } = phaseInfo(now);

  const wrapperClass = windDownMode
    ? "min-h-screen bg-black p-12 flex flex-col gap-16 font-sans text-amber-100/70 brightness-50"
    : "min-h-screen bg-black text-white p-12 flex flex-col gap-16 font-sans";

  return (
    <div className={wrapperClass}>
      <KioskTopBar />
      <KioskHero />
      {!windDownMode && <KioskCoachLine />}
      {!windDownMode && <KioskOpenList />}
      <div className="flex-1" />
      <KioskRecoverySentence />
      <KioskTagline />
    </div>
  );
}
