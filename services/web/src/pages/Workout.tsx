/**
 * Legacy /workout (singular) route — thin redirect.
 *
 * Resolves the active treadmill session and redirects to
 * /workouts/:source_id when active, or /workouts when idle.
 * The export name stays `WorkoutPage` so existing router imports
 * continue to work without changes.
 */
import { useQuery } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";

import { api } from "../api/client";

const ACTIVE_POLL_MS = 2000;

export function WorkoutPage() {
  const { data: active, isLoading } = useQuery({
    queryKey: ["workouts.active"],
    queryFn: api.activeWorkout,
    refetchInterval: ACTIVE_POLL_MS,
    staleTime: 0,
    gcTime: 0,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen text-neutral-500 text-sm">
        Redirecting…
      </div>
    );
  }

  if (active && active.status === "active") {
    return <Navigate to={`/workouts/${encodeURIComponent(active.source_id)}`} replace />;
  }

  return <Navigate to="/workouts" replace />;
}
