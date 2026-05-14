import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";

function fallbackLine(): string {
  return "Coach offline. Glance at the steps + checklist below.";
}

export function KioskCoachLine() {
  const q = useQuery({
    queryKey: ["coach-kiosk"],
    queryFn: api.coachKiosk,
    refetchInterval: 5 * 60_000,
    retry: 1,
  });

  const trimmed = q.data?.text?.trim() ?? "";
  const text = trimmed.length > 0 ? trimmed : fallbackLine();

  return (
    <section className="rounded-2xl border border-neutral-800 bg-neutral-950 p-8">
      <div className="text-xs uppercase tracking-widest text-neutral-500 mb-3">
        Coach
      </div>
      <div className="text-3xl leading-snug text-white">
        {text}
      </div>
    </section>
  );
}
