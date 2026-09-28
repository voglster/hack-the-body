import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { Capture, CaptureContext, CaptureSuggestion, EatingWindow } from "../api/types";
import { BottomNav } from "../components/BottomNav";
import { useVoiceRecorder } from "../hooks/useVoiceRecorder";

const UNDO_MS = 6000;

interface Toast { captureId?: string; label: string }

function useWakeLock(enabled: boolean) {
  useEffect(() => {
    if (!enabled || !("wakeLock" in navigator)) return;
    let lock: WakeLockSentinel | null = null;
    const acquire = () => {
      navigator.wakeLock.request("screen").then((l) => { lock = l; }).catch(() => undefined);
    };
    acquire();
    const onVisible = () => { if (document.visibilityState === "visible") acquire(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      void lock?.release();
    };
  }, [enabled]);
}

export function LogPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const kitchen = params.get("kitchen") === "1";
  const device = kitchen ? "kitchen" : "phone";
  useWakeLock(kitchen);

  const qc = useQueryClient();
  const today = useQuery({
    queryKey: ["capture.today"],
    queryFn: api.captureToday,
    refetchInterval: (q) =>
      q.state.data?.captures.some((c) => c.status === "pending") ? 2000 : 30_000,
  });
  const inbox = useQuery({ queryKey: ["capture.inbox"], queryFn: api.captureInbox, refetchInterval: 30_000 });
  const ctx = useQuery({ queryKey: ["capture.context"], queryFn: api.captureContext, refetchInterval: 60_000 });

  const [toast, setToast] = useState<Toast | null>(null);
  const [error, setError] = useState<string | null>(null);
  const toastTimer = useRef<number | undefined>(undefined);

  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["capture.today"] });
    void qc.invalidateQueries({ queryKey: ["capture.inbox"] });
    void qc.invalidateQueries({ queryKey: ["capture.context"] });
    void qc.invalidateQueries({ queryKey: ["meals.today.entries"] });
    void qc.invalidateQueries({ queryKey: ["meals.today.totals"] });
  };

  const showToast = (t: Toast) => {
    window.clearTimeout(toastTimer.current);
    setToast(t);
    toastTimer.current = window.setTimeout(() => setToast(null), UNDO_MS);
  };

  const captured = (cap: Capture, label: string) => {
    setError(null);
    showToast({ captureId: cap.id, label });
    refresh();
  };

  const capture = useMutation({
    mutationFn: (args: { body: Parameters<typeof api.capture>[0]; label: string }) =>
      api.capture({ ...args.body, device }),
    onSuccess: (cap, args) => captured(cap, args.label),
    onError: (e) => setError(e.message),
  });

  const undo = useMutation({
    mutationFn: (id: string) => api.undoCapture(id),
    onSuccess: () => { setToast(null); refresh(); },
  });

  const water = useMutation({
    mutationFn: (oz: number) => api.logWater(oz),
    onSuccess: (_e, oz) => { setError(null); refresh(); showToast({ label: `💧 ${oz} oz` }); },
  });
  const vitamins = useMutation({
    mutationFn: api.markVitaminsTaken,
    onSuccess: () => { refresh(); showToast({ label: "💊 Vitamins" }); },
  });

  const tapSuggestion = (s: CaptureSuggestion) => {
    const body = s.kind === "template"
      ? { template_id: s.template_id }
      : { food_id: s.food_id, quantity_g: s.quantity_g };
    capture.mutate({ body, label: s.name });
  };

  return (
    <div className={`min-h-screen bg-neutral-950 text-neutral-100 ${kitchen ? "p-6" : "p-4"} pb-28`}>
      <LogHeader kitchen={kitchen} totals={today.data?.totals} unresolved={today.data?.unresolved ?? 0}
                 window={ctx.data?.window} />

      <DayChips ctx={ctx.data} onWater={(oz) => water.mutate(oz)} onVitamins={() => vitamins.mutate()}
                onAte={() => capture.mutate({ body: { placeholder: true }, label: "Ate something — fill in later" })} />

      <Inbox captures={inbox.data ?? []} onChanged={refresh} />

      <CaptureBar device={device} onCaptured={(c) => captured(c, `“${c.input.text ?? ""}”`)}
                  onError={setError} />
      {error && <p className="text-amber-400 text-sm mt-2">{error}</p>}

      <SuggestionGrid items={ctx.data?.suggestions ?? []} kitchen={kitchen} disabled={capture.isPending}
                      onTap={tapSuggestion} />

      {ctx.data && <ClosedNote w={ctx.data.window} />}

      <TodayList captures={today.data?.captures ?? []} onUndo={(id) => undo.mutate(id)} />

      {toast && (<UndoToast toast={toast} onUndo={(id) => undo.mutate(id)} />)}
      <BottomNav active="log" onChange={(t) => { void navigate(`/${t}`); }} />
    </div>
  );
}

function clock(hhmm: string): string {
  const [h, m] = hhmm.split(":").map(Number);
  const suffix = h >= 12 ? "pm" : "am";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return m ? `${h12}:${String(m).padStart(2, "0")}${suffix}` : `${h12}${suffix}`;
}

function duration(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h}h ${m}m` : `${m}m`;
}

function WindowLine({ w }: { w: EatingWindow }) {
  if (w.state === "open") {
    return <span className="text-emerald-400">Eating window open · closes {clock(w.end)} ({duration(w.minutes_to_change)} left)</span>;
  }
  if (w.state === "before") {
    return <span className="text-sky-400">Fasting · window opens {clock(w.start)} (in {duration(w.minutes_to_change)})</span>;
  }
  return <span className="text-neutral-500">Window closed at {clock(w.end)} · fasting till {clock(w.start)}</span>;
}

function SuggestionGrid({ items, kitchen, disabled, onTap }: {
  items: CaptureSuggestion[]; kitchen: boolean; disabled: boolean; onTap: (s: CaptureSuggestion) => void;
}) {
  return (
    <section className={`grid gap-3 mt-4 ${kitchen ? "grid-cols-4" : "grid-cols-2 md:grid-cols-4"}`}>
      {items.map((s) => (
        <button
          key={`${s.kind}:${s.food_id ?? s.template_id}`}
          onClick={() => onTap(s)}
          disabled={disabled}
          className={`rounded-2xl bg-neutral-800 active:bg-emerald-700 px-3 ${kitchen ? "py-8 text-lg" : "py-6"}
            font-medium text-left leading-tight disabled:opacity-60`}
        >
          {s.name}
          {s.kind === "template" && <span className="block text-xs text-neutral-400 mt-1">usual</span>}
        </button>
      ))}
    </section>
  );
}

function DayChips({ ctx, onWater, onVitamins, onAte }: {
  ctx?: CaptureContext; onWater: (oz: number) => void; onVitamins: () => void; onAte: () => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 mb-4">
      <span className="text-neutral-400 tabular-nums">
        💧 {ctx?.water_oz ?? 0}/{ctx?.water_goal_oz ?? 100} oz
      </span>
      {[8, 16].map((oz) => (
        <Chip key={oz} onClick={() => onWater(oz)}>+{oz}</Chip>
      ))}
      {ctx && !ctx.vitamins_done && <Chip onClick={onVitamins}>💊 Vitamins</Chip>}
      <Chip onClick={onAte}>🍽 I just ate</Chip>
    </div>
  );
}

function ClosedNote({ w }: { w: EatingWindow }) {
  if (w.state === "open") return null;
  return (
    <p className="text-neutral-500 mt-3">
      Eating window {w.state === "before" ? "opens" : "reopens"} at {clock(w.start)}. Water, coffee, tea only.
      Anything you do eat still gets logged.
    </p>
  );
}

function LogHeader({ kitchen, totals, unresolved, window: w }: {
  kitchen: boolean; totals?: { calories: number; protein_g: number }; unresolved: number;
  window?: EatingWindow;
}) {
  return (
    <header className="flex items-baseline justify-between mb-4">
      <div>
        <h1 className={`${kitchen ? "text-3xl" : "text-2xl"} font-semibold`}>Log</h1>
        <p className="text-neutral-400 tabular-nums">
          {totals ? `${Math.round(totals.calories)} kcal · ${Math.round(totals.protein_g)} g protein` : "…"}
          {unresolved > 0 && <span className="text-amber-400"> · +{unresolved} unresolved</span>}
        </p>
        {w && <p className="text-sm mt-0.5"><WindowLine w={w} /></p>}
      </div>
    </header>
  );
}

function UndoToast({ toast, onUndo }: { toast: Toast; onUndo: (captureId: string) => void }) {
  const { captureId } = toast;
  return (
    <div className="fixed bottom-20 inset-x-4 z-30 mx-auto max-w-md rounded-xl bg-neutral-800 border border-neutral-700
                    px-4 py-3 flex items-center justify-between shadow-lg">
      <span className="truncate">✓ {toast.label}</span>
      {captureId && (
        <button onClick={() => onUndo(captureId)} className="text-emerald-400 font-semibold ml-4">
          Undo
        </button>
      )}
    </div>
  );
}

function Chip({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button onClick={onClick}
            className="rounded-full bg-neutral-900 border border-neutral-700 active:bg-neutral-700 px-4 py-2">
      {children}
    </button>
  );
}

function CaptureBar({ device, onCaptured, onError }: {
  device: string; onCaptured: (c: Capture) => void; onError: (m: string) => void;
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
  const canRecord = recorder.state !== "unsupported" && recorder.state !== "denied";

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const t = text.trim();
    if (!t) return;
    setText("");
    try { onCaptured(await api.capture({ text: t, device })); }
    catch (err) { setText(t); onError((err as Error).message); }
  };

  return (
    <form onSubmit={(e) => { void submit(e); }} className="flex gap-2">
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="What did you eat?"
        enterKeyHint="send"
        className="flex-1 rounded-2xl bg-neutral-900 border border-neutral-700 px-4 py-4 text-lg outline-none
                   focus:border-emerald-500"
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

function Inbox({ captures, onChanged }: { captures: Capture[]; onChanged: () => void }) {
  const [fill, setFill] = useState<Record<string, string>>({});
  if (captures.length === 0) return null;
  const confirm = async (id: string, body: Parameters<typeof api.confirmCapture>[1]) => {
    await api.confirmCapture(id, body);
    onChanged();
  };
  const time = (ts: string) => new Date(ts).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

  return (
    <section className="flex flex-col gap-2 mb-4">
      {captures.map((c) => (
        <div key={c.id} className="rounded-2xl border border-amber-700/60 bg-amber-950/30 p-3">
          {c.status === "needs_confirm" && (c.items ?? []).map((it, idx) => it.status === "ask" && (
            <div key={idx}>
              <p className="text-sm text-amber-200 mb-2">“{it.text}” — which one?</p>
              <div className="flex flex-wrap gap-2">
                {(it.candidates ?? []).map((cand, ci) => (
                  <button key={cand.food_id} onClick={() => { void confirm(c.id, { item_index: idx, candidate_index: ci }); }}
                          className="rounded-xl bg-neutral-800 active:bg-emerald-700 px-3 py-2 text-left">
                    {cand.name}
                  </button>
                ))}
                <button onClick={() => { void confirm(c.id, { item_index: idx, use_estimate: true }); }}
                        className="rounded-xl bg-neutral-900 border border-neutral-700 px-3 py-2">
                  Something else (estimate)
                </button>
              </div>
            </div>
          ))}
          {(c.status === "placeholder" || c.status === "failed") && (
            <form onSubmit={(e) => {
              e.preventDefault();
              const t = (fill[c.id] ?? "").trim();
              if (t) void confirm(c.id, { text: t });
            }}>
              <p className="text-sm text-amber-200 mb-2">
                {c.status === "placeholder"
                  ? `What did you eat at ${time(c.ts)}?`
                  : `Couldn't work out “${c.input.text ?? ""}” — say it another way?`}
              </p>
              <div className="flex gap-2">
                <input value={fill[c.id] ?? ""} onChange={(e) => setFill({ ...fill, [c.id]: e.target.value })}
                       className="flex-1 rounded-xl bg-neutral-900 border border-neutral-700 px-3 py-2" />
                <button className="rounded-xl bg-emerald-700 px-4">Log</button>
                <button type="button" onClick={() => { void api.undoCapture(c.id).then(onChanged); }}
                        className="rounded-xl bg-neutral-800 px-3" aria-label="dismiss">✕</button>
              </div>
            </form>
          )}
        </div>
      ))}
    </section>
  );
}

const STATUS_CHIP: Record<Capture["status"], string> = {
  resolved: "", pending: "working…", needs_confirm: "needs you", placeholder: "fill in", failed: "failed",
};

function TodayList({ captures, onUndo }: { captures: Capture[]; onUndo: (id: string) => void }) {
  if (captures.length === 0) return null;
  return (
    <section className="mt-6">
      <h2 className="text-xs uppercase tracking-wide text-neutral-500 mb-2">Today</h2>
      <ul className="divide-y divide-neutral-900">
        {captures.map((c) => {
          const names = (c.entries ?? []).map((e) => e.food_name);
          const kcal = (c.entries ?? []).reduce((s, e) => s + (e.macros.calories ?? 0), 0);
          const label = names.length ? names.join(", ") : c.input.text ?? "Ate something";
          return (
            <li key={c.id} className="flex items-center justify-between py-2 gap-3">
              <div className="min-w-0">
                <p className="truncate">{label}</p>
                <p className="text-xs text-neutral-500">
                  {new Date(c.ts).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
                  {kcal > 0 && ` · ${Math.round(kcal)} kcal`}
                  {STATUS_CHIP[c.status] && <span className="text-amber-400"> · {STATUS_CHIP[c.status]}</span>}
                </p>
              </div>
              <button onClick={() => onUndo(c.id)} className="text-neutral-600 px-2" aria-label="remove">✕</button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
