import { formatLocalDay, shiftLocalISO, todayLocalISO } from "../lib/tz";

const FLOOR_DAYS = 30;

export function DayNav({ day, onChange }: { day: string; onChange: (d: string) => void }) {
  const today = todayLocalISO();
  const floor = shiftLocalISO(today, -FLOOR_DAYS);
  const atToday = day === today;
  const atFloor = day <= floor;
  const label = atToday ? "Today" : formatLocalDay(day);

  return (
    <div className="flex items-center justify-between gap-2 mb-2">
      <button
        onClick={() => onChange(shiftLocalISO(day, -1))}
        disabled={atFloor}
        aria-label="previous day"
        className="px-3 py-2 min-h-[44px] min-w-[44px] text-neutral-300 active:text-white disabled:opacity-30"
      >
        ◀
      </button>
      <div className="flex-1 text-center text-sm font-medium text-neutral-200 tabular-nums">
        {label}
      </div>
      {!atToday && (
        <button
          onClick={() => onChange(today)}
          aria-label="jump to today"
          className="px-3 py-2 min-h-[44px] text-xs uppercase tracking-wide text-emerald-300 active:text-emerald-200"
        >
          today
        </button>
      )}
      <button
        onClick={() => onChange(shiftLocalISO(day, 1))}
        disabled={atToday}
        aria-label="next day"
        className="px-3 py-2 min-h-[44px] min-w-[44px] text-neutral-300 active:text-white disabled:opacity-30"
      >
        ▶
      </button>
    </div>
  );
}
