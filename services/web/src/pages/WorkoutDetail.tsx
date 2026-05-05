/**
 * WorkoutDetail page — handles strength, cardio, and live treadmill.
 *
 * Reads :sourceId from the route. If the active workout's source_id
 * matches and it's still "active", delegates to ActiveTreadmillView.
 * Otherwise renders a static summary appropriate to the activity_type.
 */
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { api } from "../api/client";
import { ActiveTreadmillView } from "../components/ActiveTreadmillView";
import { StrengthSetTable } from "../components/StrengthSetTable";
import type { WorkoutDetail } from "../api/types";

const ACTIVE_POLL_MS = 2000;

function fmtDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${r}s`;
  return `${r}s`;
}

function fmtDistance(meters: number | null): string | null {
  if (meters == null) return null;
  const mi = meters / 1609.344;
  return mi >= 0.1 ? `${mi.toFixed(2)} mi` : `${Math.round(meters)} m`;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-neutral-500">{label}</div>
      <div className="text-base font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function CardioSummary({ detail }: { detail: WorkoutDetail }) {
  return (
    <section className="rounded-2xl bg-neutral-900 border border-neutral-800 p-4 sm:p-6">
      <div className="text-xs uppercase tracking-wide text-neutral-400 mb-3">Summary</div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-4 gap-y-3 text-sm">
        {detail.distance_m != null && (
          <Stat label="distance" value={fmtDistance(detail.distance_m) ?? "—"} />
        )}
        {detail.avg_hr != null && (
          <Stat label="avg HR" value={`${detail.avg_hr} bpm`} />
        )}
        {detail.max_hr != null && (
          <Stat label="max HR" value={`${detail.max_hr} bpm`} />
        )}
        {detail.calories != null && (
          <Stat label="calories" value={String(detail.calories)} />
        )}
        <Stat label="source" value={detail.source} />
      </div>
    </section>
  );
}

export function WorkoutDetail() {
  const { sourceId } = useParams<{ sourceId: string }>();

  const { data: detail, isLoading, isError } = useQuery({
    queryKey: ["workouts.detail", sourceId],
    queryFn: () => api.workout(sourceId!),
    enabled: !!sourceId,
  });

  const { data: active } = useQuery({
    queryKey: ["workouts.active"],
    queryFn: api.activeWorkout,
    refetchInterval: ACTIVE_POLL_MS,
    staleTime: 0,
    gcTime: 0,
  });

  const isLiveActive =
    active != null &&
    active.status === "active" &&
    active.source_id === sourceId;

  if (isLoading) {
    return (
      <div className="max-w-4xl mx-auto px-3 sm:px-4 py-4 sm:py-8 pb-24">
        <div className="p-4 text-neutral-500">Loading…</div>
      </div>
    );
  }

  if (isError || !detail) {
    return (
      <div className="max-w-4xl mx-auto px-3 sm:px-4 py-4 sm:py-8 pb-24">
        <header className="flex items-center gap-3 mb-4">
          <Link to="/workouts" className="text-neutral-400 hover:text-neutral-200 text-2xl px-2 -ml-2">‹</Link>
          <h1 className="text-lg font-semibold">Workout</h1>
        </header>
        <div className="p-4 text-rose-400">Failed to load workout.</div>
      </div>
    );
  }

  const title = detail.title ?? detail.activity_type;
  const dateStr = new Date(detail.ts).toLocaleString(undefined, {
    weekday: "short", month: "short", day: "numeric",
    hour: "numeric", minute: "2-digit",
  });

  return (
    <div className="max-w-4xl mx-auto px-3 sm:px-4 py-4 sm:py-8 space-y-4 sm:space-y-6 pb-24">
      <header className="flex items-start gap-3 sticky top-0 z-10 bg-neutral-950/95 backdrop-blur py-2 -mx-3 px-3 sm:mx-0 sm:px-0 sm:static">
        <Link
          to="/workouts"
          className="text-neutral-400 hover:text-neutral-200 text-2xl px-2 -ml-2 shrink-0"
          aria-label="back to workouts"
        >
          ‹
        </Link>
        <div className="min-w-0">
          <h1 className="text-lg sm:text-2xl font-semibold capitalize truncate">{title}</h1>
          <div className="text-xs text-neutral-500 mt-0.5">
            {dateStr} · {fmtDuration(detail.duration_s)}
          </div>
        </div>
      </header>

      {isLiveActive ? (
        <ActiveTreadmillView active={active} />
      ) : detail.activity_type === "strength" ? (
        <StrengthSetTable exercises={detail.exercises ?? []} />
      ) : (
        <CardioSummary detail={detail} />
      )}
    </div>
  );
}
