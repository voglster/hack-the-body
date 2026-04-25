/**
 * Browser-side auth.
 *
 * The site password is also the API key — same secret. The browser POSTs the
 * candidate to /auth/verify; if accepted, we cache it in localStorage and
 * send it on every subsequent X-API-Key header. On any 401 from a protected
 * route the cache is cleared and the user is re-prompted.
 */

const STORAGE_KEY = "htb.apiKey";

let cached: string | null =
  typeof localStorage === "undefined" ? null : localStorage.getItem(STORAGE_KEY);

export function getApiKey(): string | null {
  return cached;
}

export function setApiKey(key: string): void {
  cached = key;
  localStorage.setItem(STORAGE_KEY, key);
}

export function clearApiKey(): void {
  cached = null;
  localStorage.removeItem(STORAGE_KEY);
  window.dispatchEvent(new Event("htb:auth-changed"));
}

declare global {
  interface Window { __HTB__?: { apiUrl?: string }; }
}

const BASE = window.__HTB__?.apiUrl ?? import.meta.env.VITE_API_URL ?? "";

export async function verifyPassword(password: string): Promise<boolean> {
  const r = await fetch(`${BASE}/auth/verify`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
  if (r.status === 200) {
    setApiKey(password);
    window.dispatchEvent(new Event("htb:auth-changed"));
    return true;
  }
  return false;
}

/**
 * Subscribe to auth state changes (sign-in / sign-out / 401-clear).
 * Returns an unsubscribe function.
 */
export function onAuthChanged(handler: () => void): () => void {
  window.addEventListener("htb:auth-changed", handler);
  return () => window.removeEventListener("htb:auth-changed", handler);
}
