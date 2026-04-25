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

function CoachBody({ display, error }: { display: DisplayMsg | null; error: Error | null }) {
  if (display) {
    return (
      <>
        <div className="text-sm whitespace-pre-wrap leading-relaxed">{display.text}</div>
        <div className="text-[10px] text-neutral-500">{display.meta}</div>
      </>
    );
  }
  if (error) {
    return <div className="text-sm text-red-400">{error.message}</div>;
  }
  return (
    <div className="text-sm text-neutral-500">
      tap “ask coach” for a quick read on your last 24 hours.
    </div>
  );
}

function HistoryList({ items }: { items: CoachRecentEntry[] }) {
  if (items.length === 0) return null;
  return (
    <ul className="space-y-3 pt-2 border-t border-neutral-800">
      {items.map((h, i) => (
        <li key={i} className="text-xs">
          <div className="text-neutral-500">
            {h.trigger} · {new Date(h.generated_at).toLocaleString()}
          </div>
          <div className="text-neutral-300 whitespace-pre-wrap">{h.text}</div>
        </li>
      ))}
    </ul>
  );
}

interface ActionsProps {
  hasHistory: boolean;
  showHistory: boolean;
  onToggleHistory: () => void;
  onWeekly: () => void;
  onAsk: () => void;
  weeklyPending: boolean;
  askPending: boolean;
  hasDisplay: boolean;
}

function CoachActions(p: ActionsProps) {
  return (
    <div className="flex items-center gap-2">
      {p.hasHistory && (
        <button
          onClick={p.onToggleHistory}
          className="text-xs px-3 py-2 rounded bg-neutral-800 active:bg-neutral-700 min-h-[44px]"
        >
          {p.showHistory ? "hide" : "history"}
        </button>
      )}
      <button
        onClick={p.onWeekly}
        disabled={p.weeklyPending || p.askPending}
        title="deep weekly review (gpt-oss:120b, slow)"
        className="text-xs px-3 py-2 rounded bg-indigo-700 active:bg-indigo-800 disabled:opacity-50 min-h-[44px]"
      >
        {p.weeklyPending ? "reviewing..." : "weekly"}
      </button>
      <button
        onClick={p.onAsk}
        disabled={p.askPending || p.weeklyPending}
        className="text-xs px-3 py-2 rounded bg-emerald-700 active:bg-emerald-800 disabled:opacity-50 min-h-[44px]"
      >
        {p.askPending ? "thinking..." : p.hasDisplay ? "again" : "ask coach"}
      </button>
    </div>
  );
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

  // Weekly review uses the heavy gpt-oss:120b on framework — slow (~5min),
  // separate button so we don't accidentally fire it.
  const weekly = useMutation({
    mutationFn: api.coachWeekly,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["coach.recent"] }),
  });

  // The mutation result is the freshest source of truth (with timing) when
  // available; fall back to the recent-list head otherwise.
  const display = pickDisplay(weekly.data ?? ask.data, latest);

  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="text-xs uppercase tracking-wide text-neutral-400">Coach</div>
        <CoachActions
          hasHistory={(history?.length ?? 0) > 1}
          showHistory={showHistory}
          onToggleHistory={() => setShowHistory(s => !s)}
          onWeekly={() => weekly.mutate()}
          onAsk={() => ask.mutate()}
          weeklyPending={weekly.isPending}
          askPending={ask.isPending}
          hasDisplay={display !== null}
        />
      </div>

      <CoachBody display={display} error={weekly.error ?? ask.error} />

      {showHistory && <HistoryList items={history?.slice(1) ?? []} />}
    </div>
  );
}
