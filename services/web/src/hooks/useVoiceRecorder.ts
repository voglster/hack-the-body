import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { downsampleTo16k, encodeWav, MAX_RECORDING_SECONDS, TARGET_SAMPLE_RATE } from "../lib/wav";

/**
 * Recording a dictation in the browser.
 *
 * `MediaRecorder`, deliberately not the Web Speech API: that ships the audio
 * to Google or Apple to be transcribed, which defeats the point of running
 * Whisper on our own hardware.
 *
 * The container is whatever the browser gives us and that is not negotiable —
 * Chrome records `audio/webm;codecs=opus`, Safari records `audio/mp4` (AAC) —
 * so the type is asked for in preference order and `decodeAudioData` handles
 * whichever we got.
 *
 * Every failure resolves to `unsupported` or `denied` rather than throwing.
 * Voice is an accelerator on a logger that works without it, so a browser that
 * cannot record must land on the typed form and not on an error.
 */

export type RecorderState = "idle" | "recording" | "unsupported" | "denied";

const PREFERRED_TYPES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/mp4",
  "audio/ogg;codecs=opus",
];

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return PREFERRED_TYPES.find((t) => MediaRecorder.isTypeSupported?.(t));
}

export interface UseVoiceRecorderOptions {
  /**
   * Called with whatever `stop()` would have returned when the 60s cap ends
   * the recording for the caller. Without this, the auto-stopped Blob is
   * unreachable — nothing else observes the cap firing — and a user who
   * talks past it loses the recording silently.
   */
  onAutoStop?: (blob: Blob | null) => void | Promise<void>;
}

export function useVoiceRecorder(options: UseVoiceRecorderOptions = {}) {
  const [state, setState] = useState<RecorderState>("idle");
  const [seconds, setSeconds] = useState(0);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onAutoStopRef = useRef(options.onAutoStop);
  useLayoutEffect(() => {
    onAutoStopRef.current = options.onAutoStop;
  });

  const cleanup = useCallback(() => {
    if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null; }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  useEffect(() => cleanup, [cleanup]);

  const start = useCallback(async () => {
    if (typeof MediaRecorder === "undefined" || !navigator.mediaDevices?.getUserMedia) {
      setState("unsupported");
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setState("denied");
      return;
    }
    streamRef.current = stream;
    chunksRef.current = [];
    const mimeType = pickMimeType();
    const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    rec.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
    recorderRef.current = rec;
    rec.start();
    setSeconds(0);
    setState("recording");
    tickRef.current = setInterval(() => setSeconds((s) => s + 1), 1000);
  }, []);

  const stop = useCallback(async (): Promise<Blob | null> => {
    const rec = recorderRef.current;
    if (!rec || rec.state === "inactive") { setState("idle"); return null; }

    const finished = new Promise<void>((resolve) => { rec.onstop = () => resolve(); });
    rec.stop();
    await finished;
    cleanup();
    setState("idle");

    const blob = new Blob(chunksRef.current, { type: rec.mimeType || "audio/webm" });
    if (blob.size === 0) return null;

    const AC = window.AudioContext ?? (window as never as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const audioCtx = new AC();
    try {
      const decoded = await audioCtx.decodeAudioData(await blob.arrayBuffer());
      const mono = decoded.getChannelData(0);
      return encodeWav(downsampleTo16k(mono, decoded.sampleRate), TARGET_SAMPLE_RATE);
    } catch {
      return null;
    } finally {
      await audioCtx.close();
    }
  }, [cleanup]);

  // The recorder stops itself at the cap so a pocket-dial cannot run forever
  // — but the resulting Blob must still reach the caller, not be discarded.
  useEffect(() => {
    if (state === "recording" && seconds >= MAX_RECORDING_SECONDS) {
      void stop().then((blob) => onAutoStopRef.current?.(blob));
    }
  }, [state, seconds, stop]);

  return { state, seconds, start, stop };
}
