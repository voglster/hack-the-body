import { KioskCoachLine } from "../components/kiosk/KioskCoachLine";
import { KioskHero } from "../components/kiosk/KioskHero";
import { KioskOpenList } from "../components/kiosk/KioskOpenList";
import { KioskRecoverySentence } from "../components/kiosk/KioskRecoverySentence";
import { KioskTagline } from "../components/kiosk/KioskTagline";
import { KioskTopBar } from "../components/kiosk/KioskTopBar";

export function Kiosk() {
  return (
    <div className="min-h-screen bg-black text-white p-12 flex flex-col gap-16 font-sans">
      <KioskTopBar />
      <KioskHero />
      <KioskCoachLine />
      <KioskOpenList />
      <div className="flex-1" />
      <KioskRecoverySentence />
      <KioskTagline />
    </div>
  );
}
