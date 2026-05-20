import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";
import { CoachText } from "../CoachText";

function fallbackLine(): string {
  return "Coach offline.";
}

export function KioskCoachLine() {
  const q = useQuery({
    queryKey: ["coach-kiosk"],
    queryFn: api.coachKiosk,
    refetchInterval: 5 * 60_000,
    retry: 1,
  });

  const coach = q.data?.coach?.trim() ?? "";
  const text = coach.length > 0 ? coach : fallbackLine();
  const anchors = q.data?.anchors ?? null;

  return (
    <section className="text-[5rem] font-normal leading-tight text-neutral-100">
      <CoachText text={text} anchors={anchors} />
    </section>
  );
}
