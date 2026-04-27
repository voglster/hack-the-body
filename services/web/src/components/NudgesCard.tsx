/**
 * Top-of-dashboard prescriptive nudges.
 *
 * Stateless source of truth lives on the server. We just render whatever
 * GET /nudges returned and call POST /nudges/dismiss on the × button. The
 * card hides itself entirely when no nudges fire — absence is the reward.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { FiredNudge } from "../api/types";

const ICONS: Record<string, string> = {
  vitamin: "💊",
  water: "💧",
  weight: "⚖️",
  steps: "🚶",
  bedtime: "🌙",
};

const SEVERITY_RING: Record<string, string> = {
  warn: "border-amber-700/60",
  info: "border-neutral-800",
};

export function NudgesCard() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["nudges"],
    queryFn: api.fetchNudges,
    refetchInterval: 60_000,
  });

  const dismiss = useMutation({
    mutationFn: (nudge_id: string) =>
      api.dismissNudge({ nudge_id, until: "end_of_day" }),
    onMutate: async (nudge_id) => {
      await qc.cancelQueries({ queryKey: ["nudges"] });
      const prev = qc.getQueryData<{ nudges: FiredNudge[] }>(["nudges"]);
      if (prev) {
        qc.setQueryData(["nudges"], {
          ...prev,
          nudges: prev.nudges.filter((n) => n.id !== nudge_id),
        });
      }
      return { prev };
    },
    onError: (_e, _id, ctx) => {
      if (ctx?.prev) qc.setQueryData(["nudges"], ctx.prev);
    },
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["nudges"] });
    },
  });

  const nudges = q.data?.nudges ?? [];
  if (q.isLoading || q.isError || nudges.length === 0) return null;

  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-4 space-y-3">
      <div className="text-xs uppercase tracking-wide text-neutral-400">Today</div>
      <ul className="space-y-2">
        {nudges.map((n) => (
          <li
            key={n.id}
            className={`flex items-start gap-3 rounded-lg border ${
              SEVERITY_RING[n.severity] ?? SEVERITY_RING.info
            } bg-neutral-900/60 px-3 py-2`}
          >
            <span aria-hidden className="text-xl leading-none mt-0.5">
              {ICONS[n.kind] ?? "•"}
            </span>
            <div className="flex-1 min-w-0">
              <div className="text-sm font-medium">{n.title}</div>
              <div className="text-xs text-neutral-400">{n.body}</div>
            </div>
            {n.dismissable && (
              <button
                aria-label={`dismiss ${n.id}`}
                className="text-neutral-500 hover:text-neutral-200 px-2 py-1 text-sm"
                onClick={() => dismiss.mutate(n.id)}
              >
                ✕
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
