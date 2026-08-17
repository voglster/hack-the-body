/**
 * Say what you ate. It gets logged. Undo is one tap.
 *
 * Deliberately auto-logs rather than showing a draft to confirm, unlike
 * `PasteFood` next to it: a confirm step costs a deliberate tap on the exact
 * action whose friction is the reason food logging lapses. Pasting a long
 * breakdown earns a review pass; saying "two eggs" does not.
 */
import { useState } from "react";

import { api } from "../api/client";
import type { MealSlot, ParsedFoodItem } from "../api/types";
import { useVoiceRecorder } from "../hooks/useVoiceRecorder";

function defaultSlot(): MealSlot {
  const h = new Date().getHours();
  if (h < 10) return "breakfast";
  if (h < 14) return "lunch";
  if (h < 16) return "snack";
  if (h < 21) return "dinner";
  return "snack";
}

interface Landed {
  transcript: string;
  items: ParsedFoodItem[];
  entryIds: string[];
}

export function VoiceFood({ onLogged, slot }: { onLogged: () => void; slot?: MealSlot }) {
  const [busy, setBusy] = useState(false);
  const [landed, setLanded] = useState<Landed | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Shared by a manual "Stop" click and the recorder's own 60s auto-stop —
  // whichever one produced the Blob, it still has to get uploaded rather
  // than silently dropped.
  const handleRecording = async (blob: Blob | null) => {
    if (!blob) { setError("nothing was recorded"); return; }
    setBusy(true); setError(null);
    try {
      const res = await api.logVoiceFood(blob, slot ?? defaultSlot());
      setLanded({
        transcript: res.transcript,
        items: res.items,
        entryIds: res.logged_entry_ids,
      });
      if (res.count > 0) onLogged();
      if (res.count === 0) setError("nothing food-like was heard");
    } catch (e) {
      setError(
        (e as Error).message === "voice-unavailable"
          ? "voice is unavailable — type it instead"
          : (e as Error).message,
      );
    } finally {
      setBusy(false);
    }
  };

  const { state, seconds, start, stop } = useVoiceRecorder({ onAutoStop: handleRecording });

  const onStop = async () => {
    const blob = await stop();
    await handleRecording(blob);
  };

  const onUndo = async () => {
    if (!landed) return;
    await Promise.all(landed.entryIds.map((id) => api.deleteEntry(id)));
    setLanded(null);
    onLogged();
  };

  if (state === "unsupported" || state === "denied") {
    return (
      <p className="text-sm text-neutral-500">
        {state === "denied" ? "microphone permission denied" : "this browser can't record"} — type it below
      </p>
    );
  }

  return (
    <section className="flex flex-col gap-2">
      {state !== "recording" ? (
        <button
          onClick={() => { void start(); }}
          disabled={busy}
          className="rounded-lg bg-neutral-800 px-4 py-3 text-left text-white disabled:opacity-50"
        >
          {busy ? "logging…" : "🎤 Speak a meal"}
        </button>
      ) : (
        <button
          onClick={() => { void onStop(); }}
          className="rounded-lg bg-red-600 px-4 py-3 text-left text-white"
        >
          ■ Stop · {seconds}s
        </button>
      )}

      {error && <p className="text-sm text-amber-500">{error}</p>}

      {landed && landed.items.length > 0 && (
        <div className="rounded-lg border border-neutral-700 p-3 text-sm">
          <p className="italic text-neutral-400">“{landed.transcript}”</p>
          <ul className="mt-2">
            {landed.items.map((i, n) => (
              <li key={n} className="flex justify-between">
                <span>{i.name}</span>
                <span className="tabular-nums text-neutral-400">
                  {i.calories != null ? `${Math.round(i.calories)} cal` : "—"}
                </span>
              </li>
            ))}
          </ul>
          <button onClick={() => { void onUndo(); }} className="mt-2 text-neutral-400 underline">
            Undo
          </button>
        </div>
      )}
    </section>
  );
}
