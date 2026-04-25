import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { CoachInsight, CoachRecentEntry } from "../api/types";

interface DisplayMsg { text: string; meta: string }

function pickDisplay(
  fresh: CoachInsight | undefined,
  latest: CoachRecentEntry | undefined,
): DisplayMsg | null {
  if (fresh) {
    return {
      text: fresh.text,
      meta: `${fresh.model} · ${(fresh.total_ms / 1000).toFixed(1)}s · ${new Date(fresh.generated_at).toLocaleTimeString()}`,
    };
  }
  if (latest) {
    return {
      text: latest.text,
      meta: `${latest.trigger} · ${new Date(latest.generated_at).toLocaleString()}`,
    };
  }
  return null;
}

/**
 * Coach panel — generates fresh insights on demand. Persists every insight on
 * the server (see app/services/coach.py); a "history" toggle exposes the
 * last few so we can see whether the coach is keeping continuity.
 *
 * No auto-refresh: LLM calls cost CPU/GPU on the LAN box.
 */
export function CoachCard() {
  const qc = useQueryClient();
  const [showHistory, setShowHistory] = useState(false);

  // The latest insight is always the head of /coach/recent. We fetch that on
  // mount so the dashboard shows continuity even without clicking 'ask coach'.
  const { data: history } = useQuery({
    queryKey: ["coach.recent"],
    queryFn: () => api.coachRecent(10),
  });
  const latest: CoachRecentEntry | undefined = history?.[0];

  const ask = useMutation({
    mutationFn: api.coachInsight,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["coach.recent"] }),
  });

  // The mutation result is the freshest source of truth (with timing) when
  // available; fall back to the recent-list head otherwise.
  const display = pickDisplay(ask.data, latest);

  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-xs uppercase tracking-wide text-neutral-400">Coach</div>
        <div className="flex items-center gap-2">
          {history && history.length > 1 && (
            <button
              onClick={() => setShowHistory(s => !s)}
              className="text-xs px-3 py-2 rounded bg-neutral-800 active:bg-neutral-700 min-h-[44px]"
            >
              {showHistory ? "hide" : "history"}
            </button>
          )}
          <button
            onClick={() => ask.mutate()}
            disabled={ask.isPending}
            className="text-xs px-3 py-2 rounded bg-emerald-700 active:bg-emerald-800 disabled:opacity-50 min-h-[44px]"
          >
            {ask.isPending ? "thinking..." : display ? "again" : "ask coach"}
          </button>
        </div>
      </div>

      {ask.error && !display && (
        <div className="text-sm text-red-400">{ask.error.message}</div>
      )}

      {display && (
        <>
          <div className="text-sm whitespace-pre-wrap leading-relaxed">{display.text}</div>
          <div className="text-[10px] text-neutral-500">{display.meta}</div>
        </>
      )}

      {!display && !ask.error && (
        <div className="text-sm text-neutral-500">
          tap “ask coach” for a quick read on your last 24 hours.
        </div>
      )}

      {showHistory && history && history.length > 1 && (
        <ul className="space-y-3 pt-2 border-t border-neutral-800">
          {history.slice(1).map((h, i) => (
            <li key={i} className="text-xs">
              <div className="text-neutral-500">
                {h.trigger} · {new Date(h.generated_at).toLocaleString()}
              </div>
              <div className="text-neutral-300 whitespace-pre-wrap">{h.text}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
