/**
 * Full notifications panel for the More tab. Handles subscribe/test/
 * unsubscribe — the version that lives on Today auto-hides once granted,
 * so we needed somewhere users could still reach the controls.
 */
import { useEffect, useState } from "react";

import { api } from "../api/client";
import {
  currentSubscription, pushSupported, subscribeToPush, unsubscribeFromPush,
} from "../lib/push";

type State = "loading" | "unsupported" | "denied" | "off" | "on";

export function NotificationsSettings() {
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

  return (
    <div className="rounded-xl bg-neutral-900 border border-neutral-800 p-4 space-y-2">
      <div className="text-xs uppercase tracking-wide text-neutral-400">Notifications</div>
      <div className="text-sm text-neutral-300">
        {state === "loading" && "checking…"}
        {state === "unsupported" && "this browser doesn't support push."}
        {state === "denied" && "blocked. enable in your browser settings, then reload."}
        {state === "off" && "enable to get a daily nudge from the coach."}
        {state === "on" && "on — coach pushes 7am · 12pm · 5pm and a weekly review Sunday 9pm."}
      </div>
      <div className="flex flex-wrap gap-2 pt-1">
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
              send test
            </button>
            <button onClick={() => { void disable(); }} disabled={busy}
              className="px-3 py-2 rounded bg-neutral-800 active:bg-neutral-700 text-sm disabled:opacity-50 min-h-[44px]">
              turn off
            </button>
          </>
        )}
      </div>
      {error && <div className="text-xs text-red-400">{error}</div>}
    </div>
  );
}
