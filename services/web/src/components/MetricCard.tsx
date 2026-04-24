interface Props {
  label: string;
  value: string;
  sub?: string;
}

export function MetricCard({ label, value, sub }: Props) {
  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-4 flex flex-col gap-1">
      <div className="text-xs uppercase tracking-wide text-neutral-400">{label}</div>
      <div className="text-3xl font-semibold tabular-nums">{value}</div>
      {sub && <div className="text-xs text-neutral-500">{sub}</div>}
    </div>
  );
}
