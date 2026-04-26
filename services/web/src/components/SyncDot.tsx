/**
 * Compact sync indicator for the header. Color = state, tap = detail
 * (sync time + last error if any). Replaces the verbose
 * "garmin: synced 12 min ago" line with one colored dot.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "../api/client";

const RELATIVE = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });

function relativeFromNow(iso: string): string {
  const ms = Date.now() - new Date(iso).getTime();
  const min = Math.round(ms / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return RELATIVE.format(-min, "minute");
  const hr = Math.round(min / 60);
  if (hr < 24) return RELATIVE.format(-hr, "hour");
  return RELATIVE.format(-Math.round(hr / 24), "day");
}

interface SyncEntry {
  started_at: string;
  status: string;
  error: string | null;
}

interface SourceStatus {
  last_ok: SyncEntry | null;
  last_error: SyncEntry | null;
}

function colorFor(s: SourceStatus | undefined): string {
  if (!s) return "bg-neutral-700";
  const ok = s.last_ok;
  const err = s.last_error;
  const hasFreshErr =
    err && (!ok || new Date(err.started_at) > new Date(ok.started_at));
  if (hasFreshErr) return "bg-red-500";
  if (!ok) return "bg-neutral-600";  // never synced
  const ageMin = (Date.now() - new Date(ok.started_at).getTime()) / 60_000;
  if (ageMin < 90) return "bg-emerald-500";
  if (ageMin < 24 * 60) return "bg-amber-500";
  return "bg-red-500";
}

export function SyncDot() {
  const { data } = useQuery({
    queryKey: ["syncStatus"],
    queryFn: api.syncStatus,
    refetchInterval: 60_000,
  });
  const [open, setOpen] = useState(false);

  const sources = data ? Object.entries(data) : [];
  // Worst-state color across all sources determines the dot.
  const dotColor = sources.length === 0
    ? "bg-neutral-700"
    : sources.map(([, s]) => colorFor(s as SourceStatus)).reduce((worst, c) => {
        const order = ["bg-emerald-500", "bg-amber-500", "bg-neutral-700", "bg-neutral-600", "bg-red-500"];
        return order.indexOf(c) > order.indexOf(worst) ? c : worst;
      }, "bg-emerald-500");

  return (
    <div className="relative">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-7 h-7 flex items-center justify-center rounded hover:bg-neutral-800 active:bg-neutral-700"
        aria-label="sync status"
      >
        <span className={`w-2.5 h-2.5 rounded-full ${dotColor}`} />
      </button>
      {open && (
        <div
          className="absolute right-0 top-full mt-1 z-30 w-64 rounded-lg bg-neutral-900 border border-neutral-800 shadow-xl p-3 space-y-2 text-xs"
          onClick={() => setOpen(false)}
        >
          {sources.length === 0 && (
            <div className="text-neutral-500">no sync data yet</div>
          )}
          {sources.map(([source, raw]) => {
            const s = raw as SourceStatus;
            const ok = s.last_ok;
            const err = s.last_error;
            const showErr = err && (!ok || new Date(err.started_at) > new Date(ok.started_at));
            return (
              <div key={source} className="flex flex-col gap-0.5">
                <div className="flex justify-between">
                  <span className="font-medium capitalize">{source}</span>
                  {ok && (
                    <span className="text-neutral-400">
                      synced {relativeFromNow(ok.started_at)}
                    </span>
                  )}
                  {!ok && <span className="text-neutral-500">never synced</span>}
                </div>
                {showErr && (
                  <span className="text-red-400 truncate" title={err.error ?? ""}>
                    error {relativeFromNow(err.started_at)}
                  </span>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
