import { useQuery } from "@tanstack/react-query";

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

export function SyncStatusFooter() {
  const { data } = useQuery({
    queryKey: ["syncStatus"],
    queryFn: api.syncStatus,
    refetchInterval: 60_000,
  });
  if (!data) return null;
  const sources = Object.entries(data);
  return (
    <div className="text-xs text-neutral-500 flex flex-wrap gap-x-4 gap-y-1 -mt-2">
      {sources.map(([source, s]) => {
        const ok = s.last_ok;
        const err = s.last_error;
        const showError =
          err && (!ok || new Date(err.started_at) > new Date(ok.started_at));
        if (showError) {
          return (
            <span key={source} className="text-red-400">
              {source}: error {relativeFromNow(err.started_at)}
            </span>
          );
        }
        if (ok) {
          return (
            <span key={source}>
              {source}: synced {relativeFromNow(ok.started_at)}
            </span>
          );
        }
        return <span key={source}>{source}: never synced</span>;
      })}
    </div>
  );
}
