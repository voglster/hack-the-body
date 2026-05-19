import { useEffect, useState } from "react";

/** Returns a Date that re-renders subscribers on an interval.
 *  Default 30s — keeps "in Nm" chips honest without burning render. */
export function useNow(intervalMs = 30_000): Date {
  const [now, setNow] = useState<Date>(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
