import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { CoachInsight } from "../api/types";

/**
 * Coach panel — generates a fresh insight on demand. Doesn't auto-refresh
 * because the LLM call costs ~2-3s and isn't free of LAN traffic. The button
 * shows the timing of the last response so you can see the model is healthy.
 */
export function CoachCard() {
  const [insight, setInsight] = useState<CoachInsight | null>(null);
  const ask = useMutation({
    mutationFn: api.coachInsight,
    onSuccess: setInsight,
  });

  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-xs uppercase tracking-wide text-neutral-400">Coach</div>
        <button
          onClick={() => ask.mutate()}
          disabled={ask.isPending}
          className="text-xs px-3 py-2 rounded bg-emerald-700 active:bg-emerald-800 disabled:opacity-50 min-h-[44px]"
        >
          {ask.isPending ? "thinking..." : insight ? "again" : "ask coach"}
        </button>
      </div>

      {ask.error && !insight && (
        <div className="text-sm text-red-400">{ask.error.message}</div>
      )}

      {insight && (
        <>
          <div className="text-sm whitespace-pre-wrap leading-relaxed">{insight.text}</div>
          <div className="text-[10px] text-neutral-500">
            {insight.model} · {(insight.total_ms / 1000).toFixed(1)}s ·{" "}
            {new Date(insight.generated_at).toLocaleTimeString()}
          </div>
        </>
      )}

      {!insight && !ask.error && (
        <div className="text-sm text-neutral-500">
          tap “ask coach” for a quick read on your last 24 hours.
        </div>
      )}
    </div>
  );
}
