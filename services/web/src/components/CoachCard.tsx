import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { CoachFeedbackRating, CoachInsight, CoachRecentEntry } from "../api/types";

interface DisplayMsg { id: string | null; text: string; meta: string }

function pickDisplay(
  fresh: CoachInsight | undefined,
  latest: CoachRecentEntry | undefined,
): DisplayMsg | null {
  if (fresh) {
    return {
      id: fresh.id,
      text: fresh.text,
      meta: `${fresh.model} · ${(fresh.total_ms / 1000).toFixed(1)}s · ${new Date(fresh.generated_at).toLocaleTimeString()}`,
    };
  }
  if (latest) {
    return {
      id: latest.id,
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
        {display.id && <FeedbackRow key={display.id} insightId={display.id} />}
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
    </div>
  );
}
