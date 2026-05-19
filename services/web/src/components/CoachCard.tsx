import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import { CoachChatPanel } from "./CoachChatPanel";
import { CoachText } from "./CoachText";
import type { CoachFeedbackRating, CoachFoodTotals, CoachInsight, CoachRecentEntry } from "../api/types";

interface DisplayMsg {
  id: string | null;
  text: string;
  meta: string;
  food_totals?: CoachFoodTotals | null;
  anchors?: Record<string, string> | null;
  acked_at?: string | null;
}

function pickDisplay(
  fresh: CoachInsight | undefined,
  latest: CoachRecentEntry | undefined,
): DisplayMsg | null {
  if (fresh) {
    return {
      id: fresh.id,
      text: fresh.text,
      meta: `${fresh.model} · ${(fresh.total_ms / 1000).toFixed(1)}s · ${new Date(fresh.generated_at).toLocaleTimeString()}`,
      food_totals: fresh.food_totals,
      anchors: fresh.anchors ?? null,
      acked_at: fresh.acked_at ?? null,
    };
  }
  if (latest) {
    return {
      id: latest.id,
      text: latest.text,
      meta: `${latest.trigger} · ${new Date(latest.generated_at).toLocaleString()}`,
      food_totals: latest.food_totals,
      anchors: latest.anchors ?? null,
      acked_at: latest.acked_at ?? null,
    };
  }
  return null;
}

/** "What the model saw" — collapsed by default; kept tight so it's a
 *  reference, not the headline. Catches data-pipeline bugs (e.g. wrong
 *  local-day window inflating calories) that the coach text alone hides. */
function ModelInputs({ food_totals }: { food_totals?: CoachFoodTotals | null }) {
  if (!food_totals) return null;
  const parts: string[] = [];
  if (food_totals.calories != null) parts.push(`${Math.round(food_totals.calories)} cal`);
  if (food_totals.protein_g != null) parts.push(`${Math.round(food_totals.protein_g)}g P`);
  if (food_totals.carbs_g != null) parts.push(`${Math.round(food_totals.carbs_g)}g C`);
  if (food_totals.fat_g != null) parts.push(`${Math.round(food_totals.fat_g)}g F`);
  if (food_totals.water_oz != null) parts.push(`${Math.round(food_totals.water_oz)} oz water`);
  if (food_totals.entries != null) parts.push(`${food_totals.entries} entries`);
  if (parts.length === 0) return null;
  return (
    <details className="text-[11px] text-neutral-500">
      <summary className="cursor-pointer select-none hover:text-neutral-300">
        what the model saw
      </summary>
      <div className="pt-1 pl-1 font-mono text-neutral-400">{parts.join(" · ")}</div>
    </details>
  );
}

function AckRow({
  insightId,
  ackedAt,
}: {
  insightId: string;
  ackedAt: string | null;
}) {
  const qc = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => api.coachAck(insightId),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["coach.recent"] });
    },
  });
  if (ackedAt) {
    return (
      <div className="text-[11px] text-neutral-500 pt-1">
        acknowledged at {new Date(ackedAt).toLocaleTimeString()}
      </div>
    );
  }
  return (
    <div className="pt-1">
      <button
        type="button"
        onClick={() => mutation.mutate()}
        disabled={mutation.isPending}
        className="text-xs px-3 py-1.5 rounded bg-neutral-800 active:bg-neutral-700 disabled:opacity-50"
        aria-label="acknowledge coach message"
      >
        {mutation.isPending ? "acking…" : "✓ got it"}
      </button>
    </div>
  );
}

function CoachBody({ display, error }: { display: DisplayMsg | null; error: Error | null }) {
  if (display) {
    return (
      <>
        <div className="text-sm whitespace-pre-wrap leading-relaxed">
          <CoachText text={display.text} anchors={display.anchors} />
        </div>
        <div className="text-[10px] text-neutral-500">{display.meta}</div>
        <ModelInputs food_totals={display.food_totals} />
        {display.id && <AckRow insightId={display.id} ackedAt={display.acked_at ?? null} />}
        {display.id && <FeedbackRow key={display.id} insightId={display.id} />}
      </>
    );
  }
  if (error) {
    return <div className="text-sm text-red-400">{error.message}</div>;
  }
  return (
    <div className="text-sm text-neutral-500">
      tap "ask coach" for a quick read on your last 24 hours.
    </div>
  );
}

/** Tiny thumbs-up / thumbs-down row under each rendered coach message.
 *  Down-vote opens a textarea so the user can say *why* — that note is
 *  what the review skill mines to propose SYSTEM_PROMPT edits. */
function FeedbackRow({ insightId }: { insightId: string }) {
  const [submitted, setSubmitted] = useState<CoachFeedbackRating | null>(null);
  const [showNote, setShowNote] = useState(false);
  const [note, setNote] = useState("");

  const send = useMutation({
    mutationFn: ({ rating, n }: { rating: CoachFeedbackRating; n: string }) =>
      api.coachFeedback(insightId, rating, n.trim() || undefined),
    onSuccess: (_data, vars) => {
      setSubmitted(vars.rating);
      setShowNote(false);
    },
  });

  // Reset state when the insight rotates (different id mounts a new component
  // instance via React key, but be defensive).
  const handleUp = () => {
    if (send.isPending) return;
    send.mutate({ rating: "up", n: "" });
  };
  const handleDown = () => {
    if (send.isPending) return;
    setShowNote(true);
  };
  const handleSubmitDown = () => {
    if (send.isPending) return;
    send.mutate({ rating: "down", n: note });
  };

  if (submitted) {
    return (
      <div className="text-[11px] text-neutral-500 pt-1">
        thanks — feedback saved {submitted === "down" && "(coach will tune up next review)"}
      </div>
    );
  }
  return (
    <div className="pt-1 space-y-2">
      <div className="flex items-center gap-2 text-[11px] text-neutral-500">
        <span>useful?</span>
        <button
          type="button"
          onClick={handleUp}
          disabled={send.isPending}
          aria-label="thumbs up"
          className="px-2 py-1 rounded bg-neutral-800 active:bg-neutral-700 disabled:opacity-50"
        >
          👍
        </button>
        <button
          type="button"
          onClick={handleDown}
          disabled={send.isPending}
          aria-label="thumbs down"
          className="px-2 py-1 rounded bg-neutral-800 active:bg-neutral-700 disabled:opacity-50"
        >
          👎
        </button>
        {send.error && <span className="text-red-400">save failed</span>}
      </div>
      {showNote && (
        <div className="space-y-2">
          <textarea
            value={note}
            onChange={e => setNote(e.target.value)}
            placeholder="what was wrong? (e.g. 'said I fasted but I just hadn't logged')"
            rows={2}
            className="w-full text-xs px-2 py-2 rounded bg-neutral-800 border border-neutral-700 text-neutral-200 placeholder:text-neutral-500"
          />
          <div className="flex gap-2 text-xs">
            <button
              type="button"
              onClick={handleSubmitDown}
              disabled={send.isPending}
              className="px-3 py-1.5 rounded bg-amber-700 active:bg-amber-800 text-white disabled:opacity-50"
            >
              {send.isPending ? "sending…" : "send"}
            </button>
            <button
              type="button"
              onClick={() => { setShowNote(false); setNote(""); }}
              disabled={send.isPending}
              className="px-3 py-1.5 rounded bg-neutral-800 active:bg-neutral-700 text-neutral-300"
            >
              cancel
            </button>
          </div>
        </div>
      )}
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

function renderCollapsed(
  display: DisplayMsg | null,
  expanded: boolean,
  askPending: boolean,
  weeklyPending: boolean,
  onExpand: () => void,
): React.ReactElement | null {
  if (expanded || askPending || weeklyPending) return null;
  if (!display) {
    return (
      <button
        onClick={onExpand}
        className="w-full text-left text-sm text-neutral-400 hover:text-neutral-200 px-4 py-3 rounded-xl bg-neutral-900 border border-neutral-800"
      >
        coach is quiet — tap to ask
      </button>
    );
  }
  const firstLine = display.text.split("\n").find(l => l.trim()) ?? display.text;
  return (
    <button
      onClick={onExpand}
      className="w-full text-left rounded-xl bg-neutral-900 border border-neutral-800 px-4 py-3"
    >
      <div className="text-xs uppercase tracking-wide text-neutral-400 mb-0.5">Coach</div>
      <div className="text-sm text-neutral-200 line-clamp-2">{firstLine}</div>
    </button>
  );
}

/**
 * Coach panel — when it has a message it collapses to a 1-line preview;
 * tap to expand for full text + action buttons + history. When empty,
 * shows a small CTA to ask for a fresh insight.
 *
 * No auto-refresh: LLM calls cost CPU/GPU on the LAN box.
 */
export function CoachCard() {
  const qc = useQueryClient();
  const [showHistory, setShowHistory] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const { data: history } = useQuery({
    queryKey: ["coach.recent"],
    queryFn: () => api.coachRecent(10),
  });
  const latest: CoachRecentEntry | undefined = history?.[0];

  const ask = useMutation({
    mutationFn: api.coachInsight,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["coach.recent"] });
      setExpanded(true);
    },
  });
  const weekly = useMutation({
    mutationFn: api.coachWeekly,
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["coach.recent"] });
      setExpanded(true);
    },
  });

  const display = pickDisplay(weekly.data ?? ask.data, latest);

  const collapsedView = renderCollapsed(
    display, expanded, ask.isPending, weekly.isPending,
    () => setExpanded(true),
  );
  if (collapsedView) return collapsedView;

  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <button
          onClick={() => setExpanded(false)}
          className="text-xs uppercase tracking-wide text-neutral-400 active:text-neutral-200"
          aria-label="collapse coach"
        >
          Coach ▾
        </button>
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

      <CoachChatPanel />
    </div>
  );
}
