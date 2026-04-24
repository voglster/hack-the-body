import { useQuery } from "@tanstack/react-query";

import { api } from "../api/client";
import { formatDuration, formatLbs } from "../lib/format";

export function Kiosk() {
  const { data } = useQuery({
    queryKey: ["summary"],
    queryFn: api.summary,
    refetchInterval: 5 * 60_000,
  });

  const now = new Date();
  const time = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const date = now.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });

  return (
    <div className="min-h-screen bg-black text-white p-10 flex flex-col gap-10 font-sans">
      <header className="flex items-baseline justify-between">
        <div>
          <div className="text-7xl font-semibold tabular-nums">{time}</div>
          <div className="text-2xl text-neutral-400 mt-2">{date}</div>
        </div>
        <div className="text-right">
          <div className="text-lg text-neutral-500 uppercase tracking-widest">Hack the Body</div>
        </div>
      </header>

      <main className="grid grid-cols-2 gap-8 flex-1">
        <KioskMetric
          label="Weight"
          value={data?.weight ? formatLbs(data.weight.kg) : "—"}
          sub={data?.weight?.ts.slice(0, 10)}
        />
        <KioskMetric
          label="Sleep"
          value={data?.sleep ? formatDuration(data.sleep.duration_s) : "—"}
          sub={data?.sleep?.score != null ? `score ${data.sleep.score}` : undefined}
        />
        <KioskMetric
          label="HRV"
          value={data?.hrv ? `${data.hrv.rmssd_ms.toFixed(0)} ms` : "—"}
        />
        <KioskMetric
          label="VO2 Max"
          value={data?.vo2max ? data.vo2max.value.toFixed(1) : "—"}
        />
      </main>

      <footer className="text-neutral-600 text-sm">
        Coach v2 — Phase 2 (not yet built)
      </footer>
    </div>
  );
}

function KioskMetric({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="flex flex-col justify-center border border-neutral-800 rounded-2xl p-8 bg-neutral-950">
      <div className="text-xl uppercase tracking-widest text-neutral-500">{label}</div>
      <div className="text-8xl font-semibold tabular-nums mt-4">{value}</div>
      {sub && <div className="text-lg text-neutral-500 mt-2">{sub}</div>}
    </div>
  );
}
