import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";
import type { KioskUrgency } from "../../api/types";
import { KioskPhaseCard } from "./KioskPhaseCard";

const URGENCY_COLOR: Record<KioskUrgency, string> = {
  clear:   "text-emerald-400",
  action:  "text-amber-400",
  urgent:  "text-red-500",
};

export function KioskHero() {
  const q = useQuery({
    queryKey: ["coach-kiosk"],
    queryFn: api.coachKiosk,
    refetchInterval: 5 * 60_000,
    retry: 1,
  });

  const verb = q.data?.verb?.trim() ?? "";
  const qualifier = q.data?.qualifier?.trim() ?? "";
  const urgency: KioskUrgency = q.data?.urgency ?? "clear";

  if (urgency === "clear") {
    return <KioskPhaseCard />;
  }

  const displayVerb = verb.length > 0 ? verb : "CLEAR";
  const colorClass = URGENCY_COLOR[urgency];

  return (
    <section className="flex flex-col gap-4 leading-none">
      <div className={`text-[14rem] font-semibold tracking-tight ${colorClass}`}>
        {displayVerb}
      </div>
      {qualifier && (
        <div className={`text-[5rem] font-normal ${colorClass} opacity-80`}>
          {qualifier}
        </div>
      )}
    </section>
  );
}
