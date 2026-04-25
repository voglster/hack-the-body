interface Props {
  label: string;
  value: string;
  sub?: string;
  /** 0..1 progress bar. If provided, renders a thin bar under the value. */
  progress?: number;
  /** When true, treat the card as "lagging the daily target": amber bar.
   *  When false: emerald bar. Ignored if progress is undefined. */
  behindPace?: boolean;
}

export function MetricCard({ label, value, sub, progress, behindPace }: Props) {
  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-3 sm:p-4 flex flex-col gap-1">
      <div className="text-xs uppercase tracking-wide text-neutral-400">{label}</div>
      <div className="text-2xl sm:text-3xl font-semibold tabular-nums">{value}</div>
      {progress !== undefined && (
        <div className="mt-1 h-1.5 w-full rounded-full bg-neutral-800 overflow-hidden">
          <div
            className={`h-full ${behindPace ? "bg-amber-500" : "bg-emerald-500"}`}
            style={{ width: `${Math.min(100, Math.max(0, progress * 100))}%` }}
          />
        </div>
      )}
      {sub && <div className="text-xs text-neutral-500">{sub}</div>}
    </div>
  );
}
