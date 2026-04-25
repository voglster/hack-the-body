import { useEffect, useState } from "react";

import { api } from "../api/client";
import { currentSubscription, pushSupported, subscribeToPush, unsubscribeFromPush } from "../lib/push";

type State = "loading" | "unsupported" | "denied" | "off" | "on";

export function NotificationsCard() {
  const [state, setState] = useState<State>("loading");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    if (!pushSupported()) { setState("unsupported"); return; }
    if (Notification.permission === "denied") { setState("denied"); return; }
    const sub = await currentSubscription();
    setState(sub ? "on" : "off");
  };

  useEffect(() => { void refresh(); }, []);

  const enable = async () => {
    setBusy(true); setError(null);
    try { await subscribeToPush(); await refresh(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };

  const disable = async () => {
    setBusy(true); setError(null);
    try { await unsubscribeFromPush(); await refresh(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };

  const sendTest = async () => {
    setBusy(true); setError(null);
    try { await api.pushTest(); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  };

  if (state === "loading") return null;
  if (state === "unsupported") return null;  // silently hide on browsers without push

  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <div className="text-xs uppercase tracking-wide text-neutral-400">Notifications</div>
        <div className="text-sm text-neutral-300">
          {state === "on" && "Coach can ping you (7am · 12pm · 5pm)."}
          {state === "off" && "Enable to get a daily nudge from the coach."}
          {state === "denied" && "Blocked. Enable in browser settings, then reload."}
        </div>
      </div>
      <div className="flex gap-2">
        {state === "off" && (
          <button onClick={() => { void enable(); }} disabled={busy}
            className="px-4 py-2 rounded bg-emerald-700 active:bg-emerald-800 text-sm disabled:opacity-50 min-h-[44px]">
            {busy ? "..." : "enable"}
          </button>
        )}
        {state === "on" && (
          <>
            <button onClick={() => { void sendTest(); }} disabled={busy}
              className="px-3 py-2 rounded bg-neutral-800 active:bg-neutral-700 text-sm disabled:opacity-50 min-h-[44px]">
              test
            </button>
            <button onClick={() => { void disable(); }} disabled={busy}
              className="px-3 py-2 rounded bg-neutral-800 active:bg-neutral-700 text-sm disabled:opacity-50 min-h-[44px]">
              off
            </button>
          </>
        )}
      </div>
      {error && <div className="text-xs text-red-400 sm:basis-full">{error}</div>}
    </div>
  );
}
