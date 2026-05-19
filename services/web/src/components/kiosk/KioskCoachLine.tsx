import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../../api/client";
import { CoachText } from "../CoachText";

function fallbackLine(): string {
  return "Coach offline.";
}

export function KioskCoachLine() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["coach-kiosk"],
    queryFn: api.coachKiosk,
    refetchInterval: 5 * 60_000,
    retry: 1,
  });

  const coach = q.data?.coach?.trim() ?? "";
  const text = coach.length > 0 ? coach : fallbackLine();
  const anchors = q.data?.anchors ?? null;
  const ackedAt = q.data?.acked_at ?? null;

  const ack = useMutation({
    mutationFn: api.coachAckKioskLatest,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["coach-kiosk"] });
    },
  });

  return (
    <section className="text-[5rem] font-normal leading-tight text-neutral-100 space-y-6">
      <div>
        <CoachText text={text} anchors={anchors} />
      </div>
      {coach.length > 0 && (
        ackedAt ? (
          <div className="text-2xl text-neutral-500">
            ✓ acknowledged at {new Date(ackedAt).toLocaleTimeString()}
          </div>
        ) : (
          <button
            type="button"
            onClick={() => ack.mutate()}
            disabled={ack.isPending}
            className="text-3xl px-6 py-4 rounded-2xl bg-neutral-800 active:bg-neutral-700 disabled:opacity-50 text-neutral-100"
            aria-label="acknowledge"
          >
            {ack.isPending ? "acking…" : "✓ got it"}
          </button>
        )
      )}
    </section>
  );
}
