import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";
import { trackingLine } from "../../lib/trackingLine";

/** Days logged this week, and the user's own proof of why it matters. */
export function KioskLogging() {
  const { data } = useQuery({
    queryKey: ["logging-status"],
    queryFn: api.loggingStatus,
    refetchInterval: 5 * 60_000,
  });
  if (!data) return null;
  const line = trackingLine(data.weight_by_tracking);
  return (
    <section className="flex flex-col gap-2">
      <p className="text-3xl">
        <span className={data.logged_today ? "text-emerald-400" : "text-amber-400"}>
          {data.logged_today ? "Logged today" : data.lapsed ? "Log one thing today" : "Nothing logged yet today"}
        </span>
        <span className="text-neutral-500"> · {data.days_logged_7d} of 7 days this week</span>
        {data.pending > 0 && <span className="text-amber-400"> · {data.pending} to confirm</span>}
      </p>
      {line && <p className="text-2xl text-neutral-500">{line}</p>}
    </section>
  );
}
