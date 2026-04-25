/**
 * Browser-side Web Push subscribe / unsubscribe.
 *
 * Flow:
 * 1. Make sure the service worker is registered.
 * 2. Ask Notification.requestPermission() — user gets the system prompt once.
 * 3. Fetch the VAPID public key from the API.
 * 4. PushManager.subscribe() with that key as applicationServerKey.
 * 5. POST the resulting PushSubscription JSON to /push/subscribe.
 *
 * On success, returns the endpoint URL so callers can stash it (e.g. to
 * unsubscribe later).
 */

import { api } from "../api/client";

/** Decode a urlsafe-base64 VAPID public key into the typed buffer that
 *  PushManager.subscribe wants (ArrayBuffer, not SharedArrayBuffer). */
function urlBase64ToBuffer(b64: string): ArrayBuffer {
  const padding = "=".repeat((4 - (b64.length % 4)) % 4);
  const base64 = (b64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const buf = new ArrayBuffer(raw.length);
  const view = new Uint8Array(buf);
  for (let i = 0; i < raw.length; i++) view[i] = raw.charCodeAt(i);
  return buf;
}

export function pushSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

export async function getRegistration(): Promise<ServiceWorkerRegistration | null> {
  if (!("serviceWorker" in navigator)) return null;
  return navigator.serviceWorker.ready;
}

export async function currentSubscription(): Promise<PushSubscription | null> {
  const reg = await getRegistration();
  if (!reg) return null;
  return reg.pushManager.getSubscription();
}

export async function subscribeToPush(): Promise<PushSubscription> {
  if (!pushSupported()) throw new Error("push not supported in this browser");
  const reg = await getRegistration();
  if (!reg) throw new Error("service worker not registered");

  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error(`notifications ${permission}`);

  const existing = await reg.pushManager.getSubscription();
  if (existing) {
    await api.pushSubscribe(existing.toJSON());
    return existing;
  }

  const { public_key } = await api.vapidPublicKey();
  const sub = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToBuffer(public_key),
  });
  await api.pushSubscribe(sub.toJSON());
  return sub;
}

export async function unsubscribeFromPush(): Promise<void> {
  const sub = await currentSubscription();
  if (!sub) return;
  await api.pushUnsubscribe(sub.endpoint);
  await sub.unsubscribe();
}
