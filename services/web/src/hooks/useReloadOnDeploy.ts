import { useEffect } from "react";

const POLL_MS = 3 * 60_000;

async function currentBuild(): Promise<string | null> {
  try {
    const r = await fetch("/version", { cache: "no-store" });
    if (!r.ok) return null;
    return ((await r.json()) as { build?: string }).build ?? null;
  } catch {
    return null;
  }
}

/** Always-on screens reload themselves when a deploy ships a new frontend build. */
export function useReloadOnDeploy(enabled: boolean) {
  useEffect(() => {
    if (!enabled) return;
    let first: string | null = null;
    const check = async () => {
      const build = await currentBuild();
      if (!build) return;
      if (first === null) first = build;
      else if (build !== first) window.location.reload();
    };
    void check();
    const id = window.setInterval(() => { void check(); }, POLL_MS);
    return () => window.clearInterval(id);
  }, [enabled]);
}
