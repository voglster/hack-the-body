import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";
import type { CoachTurn } from "../api/types";


function TurnBubble({ turn }: { turn: CoachTurn }) {
  const isCoach = turn.role === "coach";
  return (
    <div className={isCoach ? "text-sm text-neutral-200" : "text-sm text-emerald-300"}>
      <div className="text-[10px] uppercase tracking-wide text-neutral-500 mb-0.5">
        {isCoach ? "Coach" : "You"}
      </div>
      <div className="whitespace-pre-wrap leading-relaxed">{turn.text}</div>
      {turn.tool_calls?.length ? (
        <details className="text-[11px] text-neutral-500 mt-1">
          <summary className="cursor-pointer">
            {turn.tool_calls.length} tool call{turn.tool_calls.length > 1 ? "s" : ""}
          </summary>
          <ul className="pl-2 font-mono space-y-1 mt-1">
            {turn.tool_calls.map((c, i) => (
              <li key={i}>{c.name}({JSON.stringify(c.args)})</li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

export function CoachChatPanel() {
  const qc = useQueryClient();
  const [draft, setDraft] = useState("");
  const { data: thread, isLoading } = useQuery({
    queryKey: ["coach.thread.active"],
    queryFn: () => api.coachThreadActive(),
  });

  const send = useMutation({
    mutationFn: async (text: string) => {
      if (!thread) throw new Error("no active thread");
      return api.coachThreadReply(thread.id, text);
    },
    onSuccess: () => {
      setDraft("");
      void qc.invalidateQueries({ queryKey: ["coach.thread.active"] });
    },
  });

  if (isLoading) {
    return <div className="text-xs text-neutral-500">loading thread…</div>;
  }
  if (!thread) {
    return (
      <div className="text-xs text-neutral-500">
        no active thread — ask the coach above to start one.
      </div>
    );
  }

  return (
    <div className="space-y-3 border-t border-neutral-800 pt-3">
      <div className="space-y-3 max-h-[40vh] overflow-y-auto">
        {thread.turns.map((t, i) => (
          <TurnBubble key={i} turn={t} />
        ))}
        {send.isPending && (
          <div className="text-xs text-neutral-500 italic">coach thinking…</div>
        )}
      </div>
      <form
        onSubmit={e => { e.preventDefault(); if (draft.trim()) send.mutate(draft.trim()); }}
        className="flex gap-2"
      >
        <input
          type="text"
          value={draft}
          onChange={e => setDraft(e.target.value)}
          placeholder="ask the coach…"
          disabled={send.isPending}
          className="flex-1 text-sm px-3 py-2 rounded bg-neutral-800 border border-neutral-700 text-neutral-100 placeholder:text-neutral-500"
        />
        <button
          type="submit"
          disabled={send.isPending || !draft.trim()}
          className="text-xs px-3 py-2 rounded bg-emerald-700 active:bg-emerald-800 disabled:opacity-50"
        >
          send
        </button>
      </form>
      {send.error && (
        <div className="text-xs text-red-400">{(send.error as Error).message}</div>
      )}
    </div>
  );
}
