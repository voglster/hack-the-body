/**
 * Always-visible "Steps today" hero card.
 *
 * Big number (current count), goal context, progress bar with two markers
 * (where you are vs. where you should be by now), and a one-liner that
 * answers "am I going to hit my goal?". The pace math assumes a 6am→
 * midnight walking window — anything before 6am counts as on-pace by
 * default since most people aren't out walking yet.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { api } from "../api/client";
import type { Summary } from "../api/types";
import { forecast, type Forecast } from "../lib/stepsForecast";

const STATUS_TONE: Record<Forecast["status"], { bar: string; pill: string }> = {
  early:   { bar: "bg-neutral-500",  pill: "text-neutral-400" },
  ahead:   { bar: "bg-emerald-500",  pill: "text-emerald-300" },
  "on-pace":  { bar: "bg-emerald-500", pill: "text-emerald-300" },
  behind:  { bar: "bg-amber-500",    pill: "text-amber-300" },
  miss:    { bar: "bg-red-500",      pill: "text-red-300" },
  "no-goal": { bar: "bg-neutral-500", pill: "text-neutral-400" },
};

/** Build the host <section> props. When `onOpen` is set we make the
 *  whole card a button-like surface (click + Enter/Space). Without it
 *  the card is purely presentational. Extracted so `StepsTodayCard`
 *  itself stays under the lint complexity ceiling. */
function makeCardProps(onOpen?: () => void): React.HTMLAttributes<HTMLElement> {
  if (!onOpen) {
    return {
      className: "rounded-2xl bg-neutral-900 border border-neutral-800 p-4 sm:p-6 space-y-4",
    };
  }
  return {
    className:
      "rounded-2xl bg-neutral-900 border border-neutral-800 p-4 sm:p-6 space-y-4 " +
      "cursor-pointer hover:border-neutral-700 active:bg-neutral-900/60",
    onClick: onOpen,
    onKeyDown: (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onOpen();
      }
    },
    role: "button",
    tabIndex: 0,
    "aria-label": "Steps today — open trends",
  };
}

function useStepGoal(summary: Summary | undefined): number | null {
  // User-set step_goal_override wins over Garmin's auto-tuned step_goal.
  // Both are optional: if neither is set, callers hide goal-relative UI.
  const { data: targets } = useQuery({
    queryKey: ["profile.targets"],
    queryFn: api.getTargets,
  });
  return targets?.step_goal_override ?? summary?.daily_summary?.step_goal ?? null;
}

export function StepsTodayCard({ summary, todaySteps, onOpenTrends }: {
  summary: Summary | undefined;
  todaySteps: number | undefined;
  /** Optional handler invoked when the user taps the card (anywhere
   *  except the inline sync button). Used by the Today tab to jump to
   *  the Trends tab with the steps chart pre-opened. */
  onOpenTrends?: () => void;
}) {
  const ds = summary?.daily_summary;
  const steps = todaySteps ?? ds?.steps ?? 0;
  const goal = useStepGoal(summary);
  const f = forecast(steps, goal, new Date());
  const tone = STATUS_TONE[f.status];

  const sync = useStepsSync();

  // Position of the "expected pace" marker on the bar.
  const expectedPct = goal ? Math.min(100, f.expectedFraction * 100) : 0;
  const donePct = goal ? Math.min(100, f.fractionDone * 100) : 0;

  const cardProps = makeCardProps(onOpenTrends);
  return (
    <section {...cardProps}>
      <div className="flex items-baseline justify-between gap-2">
        <div className="text-xs uppercase tracking-wide text-neutral-400 flex items-center gap-1">
          <span>Steps today</span>
          {onOpenTrends && <span className="text-neutral-600">›</span>}
        </div>
        {goal && (
          <div className="text-xs text-neutral-500 tabular-nums">
            {Math.round(f.fractionDone * 100)}% of {goal.toLocaleString()}
          </div>
        )}
      </div>

      <div className="flex items-end gap-3">
        <div className="text-5xl sm:text-6xl font-bold tabular-nums leading-none">
          {steps.toLocaleString()}
        </div>
        {goal && (
          <div className="pb-1 text-sm text-neutral-500 tabular-nums">
            / {goal.toLocaleString()}
          </div>
        )}
      </div>

      {goal && (
        <div className="relative h-2.5 w-full rounded-full bg-neutral-800 overflow-visible">
          <div
            className={`h-full rounded-full ${tone.bar}`}
            style={{ width: `${donePct}%` }}
          />
          {/* expected-pace marker (where you "should be" right now) */}
          {f.status !== "early" && (
            <div
              className="absolute top-[-3px] bottom-[-3px] w-0.5 bg-neutral-300"
              style={{ left: `${expectedPct}%` }}
              aria-label="expected pace"
              title="expected pace by now"
            />
          )}
        </div>
      )}

      <div className="flex items-center justify-between gap-3">
        <div className={`text-sm font-medium ${tone.pill}`}>{f.message}</div>
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); sync.start(); }}
          disabled={sync.busy}
          className="shrink-0 text-xs px-2.5 py-1 rounded-md bg-neutral-800 hover:bg-neutral-700 disabled:opacity-50 disabled:cursor-not-allowed text-neutral-200"
          aria-label="sync steps from Garmin"
        >
          {sync.busy ? "syncing…" : sync.justOk ? "synced ✓" : "sync steps"}
        </button>
      </div>
    </section>
  );
}

/**
 * Trigger a focused steps-only ingest, then wait for the ingestor's poll loop
 * (≤30s) to pick it up and write a new ok-log entry. We watch the sync-status
 * endpoint's last_ok timestamp; when it advances past our trigger time, we
 * invalidate the steps + summary queries so the user sees fresh data.
 */
function useStepsSync() {
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [justOk, setJustOk] = useState(false);
  const okTimeoutRef = useRef<number | null>(null);

  useEffect(() => () => {
    if (okTimeoutRef.current) window.clearTimeout(okTimeoutRef.current);
  }, []);

  const m = useMutation({
    mutationFn: async () => {
      const triggeredAt = Date.now();
      await api.triggerIngest("garmin", "steps");
      // Poll sync-status until last_ok moves forward, max ~70s
      // (poll cadence is 30s + sync ~3s + slack).
      const deadline = triggeredAt + 70_000;
      while (Date.now() < deadline) {
        await new Promise(r => setTimeout(r, 2000));
        try {
          const s = await api.syncStatus();
          const ok = s.garmin?.last_ok;
          if (ok && new Date(ok.started_at).getTime() >= triggeredAt) return;
        } catch { /* ignore transient */ }
      }
      throw new Error("sync did not complete in time");
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["stepsDay"] });
      void qc.invalidateQueries({ queryKey: ["summary"] });
      void qc.invalidateQueries({ queryKey: ["syncStatus"] });
      setJustOk(true);
      if (okTimeoutRef.current) window.clearTimeout(okTimeoutRef.current);
      okTimeoutRef.current = window.setTimeout(() => setJustOk(false), 3000);
    },
    onSettled: () => setBusy(false),
  });

  return {
    busy,
    justOk,
    start: () => {
      if (busy) return;
      setBusy(true);
      setJustOk(false);
      m.mutate();
    },
  };
}
