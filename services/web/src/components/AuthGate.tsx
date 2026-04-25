import { useEffect, useState } from "react";

import { getApiKey, onAuthChanged, verifyPassword } from "../lib/auth";

/**
 * Renders the children only when the browser holds a verified API key.
 * Otherwise shows a password form. Re-renders on auth state changes (a 401
 * elsewhere in the app clears the key — see api/client.ts handleUnauthorized).
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const [hasKey, setHasKey] = useState<boolean>(getApiKey() != null);

  useEffect(() => onAuthChanged(() => setHasKey(getApiKey() != null)), []);

  if (!hasKey) return <LoginForm />;
  return <>{children}</>;
}

function LoginForm() {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!password) return;
    setBusy(true);
    setError(null);
    try {
      const ok = await verifyPassword(password);
      if (!ok) setError("wrong password");
    } catch {
      setError("server unreachable");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-neutral-950 p-6">
      <form
        onSubmit={(e) => { void submit(e); }}
        className="w-full max-w-sm space-y-4 rounded-xl border border-neutral-800 bg-neutral-900 p-6"
      >
        <div>
          <h1 className="text-xl font-semibold">Hack the Body</h1>
          <p className="text-sm text-neutral-500 mt-1">enter the site password to continue</p>
        </div>
        <input
          type="password"
          autoFocus
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="password"
          className="w-full px-3 py-2 rounded bg-neutral-950 border border-neutral-800 text-sm"
        />
        <button
          type="submit"
          disabled={busy || !password}
          className="w-full px-3 py-2 rounded bg-emerald-700 hover:bg-emerald-600 text-sm font-medium disabled:opacity-50"
        >
          {busy ? "checking…" : "unlock"}
        </button>
        {error && <div className="text-xs text-red-400">{error}</div>}
      </form>
    </div>
  );
}
