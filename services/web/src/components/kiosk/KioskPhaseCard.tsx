import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../../api/client";
import { phaseInfo } from "../../lib/dayPhase";
import { stepStreak } from "../../lib/stepStreak";

export function KioskPhaseCard() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(id);
  }, []);

  const stepsQ = useQuery({
    queryKey: ["steps-range-streak"],
    queryFn: () => api.stepsRange(60),
    staleTime: 60 * 60_000, // streak math only needs daily resolution
  });

  const info = phaseInfo(now);
  const streak = stepStreak(stepsQ.data ?? []);

  return (
    <section className="flex flex-col gap-8 leading-none">
      <div>
        <div className="text-xl uppercase tracking-widest text-neutral-500 mb-4">
          {info.title}
        </div>
        <div className="text-[7rem] font-semibold tracking-tight text-neutral-100">
          {info.detail}
        </div>
      </div>
      {streak.current > 0 && (
        <div>
          <div className="text-xl uppercase tracking-widest text-neutral-500 mb-2">
            Step streak
          </div>
          <div className="flex items-baseline gap-6 text-[5rem] font-medium text-neutral-200">
            <span>Day {streak.current}</span>
            {streak.longest > streak.current && (
              <span className="text-neutral-500">/ longest {streak.longest}</span>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
