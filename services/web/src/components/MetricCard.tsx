interface Props {
  label: string;
  value: string;
  sub?: string;
  /** 0..1 progress bar. If provided, renders a thin bar under the value. */
  progress?: number;
  /** When true, treat the card as "lagging the daily target": amber bar.
   *  When false: emerald bar. Ignored if progress is undefined. */
  behindPace?: boolean;
  /** When set, the card becomes a clickable button — used by the Today
   *  tab to jump to the corresponding chart on the Trends tab. */
  onClick?: () => void;
}

export function MetricCard({ label, value, sub, progress, behindPace, onClick }: Props) {
  const inner = (
    <>
      <div className="text-xs uppercase tracking-wide text-neutral-400 flex items-center gap-1">
        <span>{label}</span>
        {onClick && <span className="text-neutral-600">›</span>}
      </div>
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
    </>
  );
  const baseClass = "rounded-xl bg-neutral-900 border border-neutral-800 p-3 sm:p-4 flex flex-col gap-1 text-left";
  if (onClick) {
    // Mirror StepsTodayCard's div+role=button pattern instead of using a
    // real <button>. Some mobile browsers (notably iOS Safari in PWA
    // mode) eat the click on a styled <button> inside a CSS grid before
    // React Router gets it; the role-button div is rock-solid across
    // every device we've tested.
    const onKey = (e: React.KeyboardEvent) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onClick();
      }
    };
    return (
      <div
        role="button"
        tabIndex={0}
        onClick={onClick}
        onKeyDown={onKey}
        className={`${baseClass} cursor-pointer hover:border-neutral-700 active:bg-neutral-800 transition-colors`}
        aria-label={`${label} — open trends`}
      >
        {inner}
      </div>
    );
  }
  return <div className={baseClass}>{inner}</div>;
}
