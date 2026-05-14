import { useQuery } from "@tanstack/react-query";

import { api } from "../../api/client";
import { formatDuration, formatLbs } from "../../lib/format";

export function KioskRecoveryStrip() {
  const { data } = useQuery({
    queryKey: ["summary"],
    queryFn: api.summary,
    refetchInterval: 5 * 60_000,
  });

  const sleepLabel = data?.sleep
    ? `${formatDuration(data.sleep.duration_s)}${
        data.sleep.score != null ? ` ★${data.sleep.score}` : ""
      }`
    : "—";

  return (
    <section className="flex items-center justify-around text-neutral-400 text-lg border-t border-neutral-800 pt-4">
      <Cell label="Sleep" value={sleepLabel} />
      <Cell label="HRV" value={data?.hrv ? `${data.hrv.rmssd_ms.toFixed(0)} ms` : "—"} />
      <Cell label="RHR" value={
        data?.daily_summary?.resting_hr != null
          ? `${data.daily_summary.resting_hr}`
          : "—"
      } />
      <Cell label="Weight" value={data?.weight ? formatLbs(data.weight.kg) : "—"} />
      <Cell label="VO2" value={data?.vo2max ? data.vo2max.value.toFixed(1) : "—"} />
    </section>
  );
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="text-xs uppercase tracking-widest text-neutral-500">{label}</span>
      <span className="text-xl text-white tabular-nums">{value}</span>
    </div>
  );
}
