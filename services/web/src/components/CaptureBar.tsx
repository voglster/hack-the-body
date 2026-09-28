import { useState } from "react";

import { api } from "../api/client";
import type { Capture } from "../api/types";
import { useVoiceRecorder } from "../hooks/useVoiceRecorder";

const MAX_ROWS = 6;

/**
 * The one place food gets typed, pasted, or spoken. Saves the moment you
 * press Enter — resolution happens server-side afterwards. Shift+Enter keeps
 * a pasted breakdown's lines. `ts` backdates the capture (no mic then: a
 * dictation is always "now").
 */
export function CaptureBar({ device, ts, onCaptured, onError }: {
  device: string; ts?: string; onCaptured: (c: Capture) => void; onError: (m: string) => void;
}) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  const sendVoice = async (blob: Blob | null) => {
    if (!blob) return;
    setBusy(true);
    try { onCaptured(await api.captureVoice(blob, device)); }
    catch (e) { onError((e as Error).message); }
    finally { setBusy(false); }
  };
  const recorder = useVoiceRecorder({ onAutoStop: (b) => { void sendVoice(b); } });
  const recording = recorder.state === "recording";
  const canRecord = !ts && recorder.state !== "unsupported" && recorder.state !== "denied";

  const submit = async () => {
    const t = text.trim();
    if (!t) return;
    setText("");
    try { onCaptured(await api.capture({ text: t, device, ...(ts ? { ts } : {}) })); }
    catch (err) { setText(t); onError((err as Error).message); }
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void submit();
    }
  };

  return (
    <form onSubmit={(e) => { e.preventDefault(); void submit(); }} className="flex gap-2">
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={onKeyDown}
        rows={Math.min(Math.max(text.split("\n").length, 1), MAX_ROWS)}
        placeholder="What did you eat?"
        enterKeyHint="send"
        className="flex-1 resize-none rounded-2xl bg-neutral-900 border border-neutral-700 px-4 py-4 text-lg
                   outline-none focus:border-emerald-500"
      />
      {canRecord && (
        <button
          type="button"
          disabled={busy}
          onClick={() => { void (recording ? recorder.stop().then(sendVoice) : recorder.start()); }}
          className={`rounded-2xl px-5 text-2xl ${recording ? "bg-red-600" : "bg-neutral-800"} disabled:opacity-50`}
          aria-label={recording ? "stop recording" : "record"}
        >
          {busy ? "…" : recording ? `■ ${recorder.seconds}` : "🎤"}
        </button>
      )}
    </form>
  );
}
