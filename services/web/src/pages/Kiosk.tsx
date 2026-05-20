import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { KioskCoachLine } from "../components/kiosk/KioskCoachLine";
import { KioskHero } from "../components/kiosk/KioskHero";
import { KioskOpenList } from "../components/kiosk/KioskOpenList";
import { KioskRecoverySentence } from "../components/kiosk/KioskRecoverySentence";
import { KioskTagline } from "../components/kiosk/KioskTagline";
import { KioskTopBar } from "../components/kiosk/KioskTopBar";

export function Kiosk() {
  const q = useQuery({
    queryKey: ["coach-kiosk"],
    queryFn: api.coachKiosk,
    refetchInterval: 5 * 60_000,
    retry: 1,
  });
  const windDownMode = q.data?.wind_down_mode ?? false;

  const wrapperClass = windDownMode
    ? "min-h-screen bg-black p-12 flex flex-col gap-16 font-sans text-amber-100/70 brightness-50"
    : "min-h-screen bg-black text-white p-12 flex flex-col gap-16 font-sans";

  return (
    <div className={wrapperClass}>
      <KioskTopBar />
      <KioskHero />
      <KioskCoachLine />
      {!windDownMode && <KioskOpenList />}
      <div className="flex-1" />
      <KioskRecoverySentence />
      <KioskTagline />
    </div>
  );
}
