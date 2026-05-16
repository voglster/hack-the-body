/**
 * Coach-note cards — text fields the coach reads on every generation.
 *
 *  - DayNoteCard         : ephemeral. Resets at local midnight via the
 *                          server-computed `is_today` flag. Lives on the
 *                          Today tab.
 *  - StandingProfileCard : long-lived stance / goals. Edited rarely,
 *                          tucked away under the More tab.
 *
 * Both autosave on blur. No explicit save button — the visible
 * "saved 2 min ago" line is the contract.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../api/client";

function relativeAgo(iso: string | null | undefined): string {
  if (!iso) return "not set";
  const then = new Date(iso).getTime();
  const now = Date.now();
  const sec = Math.max(0, Math.round((now - then) / 1000));
  if (sec < 60) return "just now";
  if (sec < 3600) return `${Math.floor(sec / 60)} min ago`;
  if (sec < 86_400) return `${Math.floor(sec / 3600)} hr ago`;
  return `${Math.floor(sec / 86_400)} d ago`;
}

export function DayNoteCard() {
  const qc = useQueryClient();

  const dayNoteQ = useQuery({
    queryKey: ["profile.day-note"],
    queryFn: api.getDayNote,
    refetchOnWindowFocus: true,
  });

  const [day, setDay] = useState<string>("");
  const [daySeeded, setDaySeeded] = useState(false);

  useEffect(() => {
    if (dayNoteQ.data && !daySeeded) {
      setDay(dayNoteQ.data.text);
      setDaySeeded(true);
    }
  }, [dayNoteQ.data, daySeeded]);

  const saveDay = useMutation({
    mutationFn: (text: string) => api.putDayNote(text),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["profile.day-note"] }),
  });

  const handleDayBlur = () => {
    const trimmed = day.trim();
    if (trimmed !== (dayNoteQ.data?.text ?? "")) {
      saveDay.mutate(trimmed);
    }
  };

  return (
    <div className="rounded-2xl bg-neutral-900/50 border border-neutral-800 p-4">
      <div className="flex items-baseline justify-between mb-1.5">
        <label
          htmlFor="day-note"
          className="text-xs font-medium uppercase tracking-wider text-neutral-400"
        >
          Today's note
        </label>
        <span className="text-[10px] text-neutral-500">
          {saveDay.isPending ? "saving…" : `saved ${relativeAgo(dayNoteQ.data?.set_at)}`}
        </span>
      </div>
      <input
        id="day-note"
        type="text"
        value={day}
        onChange={(e) => setDay(e.target.value)}
        onBlur={handleDayBlur}
        placeholder="dinner out tonight, eating late on purpose"
        maxLength={500}
        className="w-full bg-neutral-950/60 border border-neutral-800 rounded-lg px-3 py-2 text-sm text-neutral-100 placeholder:text-neutral-600 focus:border-neutral-600 focus:outline-none"
      />
      <p className="text-[10px] text-neutral-600 mt-1">
        Resets at midnight. The coach reads this on every generation.
      </p>
    </div>
  );
}

export function StandingProfileCard() {
  const qc = useQueryClient();

  const coachNoteQ = useQuery({
    queryKey: ["profile.coach-note"],
    queryFn: api.getCoachNote,
  });

  const [coach, setCoach] = useState<string>("");
  const [coachSeeded, setCoachSeeded] = useState(false);

  useEffect(() => {
    if (coachNoteQ.data && !coachSeeded) {
      setCoach(coachNoteQ.data.text);
      setCoachSeeded(true);
    }
  }, [coachNoteQ.data, coachSeeded]);

  const saveCoach = useMutation({
    mutationFn: (text: string) => api.putCoachNote(text),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["profile.coach-note"] }),
  });

  const handleCoachBlur = () => {
    const trimmed = coach.trim();
    if (trimmed !== (coachNoteQ.data?.text ?? "")) {
      saveCoach.mutate(trimmed);
    }
  };

  return (
    <div className="rounded-2xl bg-neutral-900/50 border border-neutral-800 p-4">
      <div className="flex items-baseline justify-between mb-1.5">
        <label
          htmlFor="coach-note"
          className="text-xs font-medium uppercase tracking-wider text-neutral-400"
        >
          Standing profile
        </label>
        <span className="text-[10px] text-neutral-500">
          {saveCoach.isPending
            ? "saving…"
            : `saved ${relativeAgo(coachNoteQ.data?.updated_at)}`}
        </span>
      </div>
      <textarea
        id="coach-note"
        value={coach}
        onChange={(e) => setCoach(e.target.value)}
        onBlur={handleCoachBlur}
        placeholder="Trying to lose weight slowly. Low calories alone is fine — flag only when paired with low protein or high activity."
        maxLength={2000}
        rows={4}
        className="w-full bg-neutral-950/60 border border-neutral-800 rounded-lg px-3 py-2 text-sm text-neutral-100 placeholder:text-neutral-600 focus:border-neutral-600 focus:outline-none resize-y"
      />
      <p className="text-[10px] text-neutral-600 mt-1">
        Your standing stance and overall goal — edit rarely. The coach uses it to interpret today's numbers.
      </p>
    </div>
  );
}
