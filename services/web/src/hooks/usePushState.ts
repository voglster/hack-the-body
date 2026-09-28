import { useCallback, useEffect, useState } from "react";

import { currentSubscription, pushSupported } from "../lib/push";

export type PushState = "loading" | "unsupported" | "denied" | "off" | "on";

function knownWithoutSubscription(): PushState | null {
  if (!pushSupported()) return "unsupported";
  if (Notification.permission === "denied") return "denied";
  return null;
}

async function subscriptionState(): Promise<PushState> {
  return (await currentSubscription()) ? "on" : "off";
}

export function usePushState(): [PushState, () => Promise<void>] {
  const [state, setState] = useState<PushState>(() => knownWithoutSubscription() ?? "loading");

  useEffect(() => {
    if (knownWithoutSubscription() === null) void subscriptionState().then(setState);
  }, []);

  const refresh = useCallback(async () => {
    setState(knownWithoutSubscription() ?? await subscriptionState());
  }, []);

  return [state, refresh];
}
