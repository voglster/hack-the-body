import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";

function fmtTime(iso: string): string {
  const d = new Date(iso);
  const h = d.getHours();
  const m = d.getMinutes().toString().padStart(2, "0");
  const ampm = h >= 12 ? "p" : "a";
  return `${h % 12 === 0 ? 12 : h % 12}:${m}${ampm}`;
}

export function VitaminsCard() {
  const qc = useQueryClient();
  const today = useQuery({
    queryKey: ["vitamins.today"],
    queryFn: api.vitaminsToday,
    refetchInterval: 60_000,
  });
  const log = useMutation({
    mutationFn: api.logVitamins,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["vitamins.today"] });
      void qc.invalidateQueries({ queryKey: ["meals.today.entries"] });
      void qc.invalidateQueries({ queryKey: ["meals.today.totals"] });
    },
  });

  const logged = today.data?.logged ?? false;
  const ts = today.data?.first_ts ?? null;

  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-4 flex items-center gap-3">
      <div className="flex-1 min-w-0">
        <div className="text-xs uppercase tracking-wide text-neutral-400">Vitamins</div>
        <div className="text-lg font-semibold">
          {logged
            ? <span className="text-emerald-400">✓ taken{ts ? ` at ${fmtTime(ts)}` : ""}</span>
            : <span className="text-neutral-400">not yet today</span>}
        </div>
      </div>
      {!logged && (
        <button
          onClick={() => log.mutate()}
          disabled={log.isPending}
          className="px-4 py-3 rounded bg-amber-700 active:bg-amber-800 text-white text-sm font-medium disabled:opacity-50 min-h-[44px]"
        >
          {log.isPending ? "..." : "took 'em"}
        </button>
      )}
    </div>
  );
}
