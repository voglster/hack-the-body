import { useEffect, useRef, useState } from "react";

/* Native BarcodeDetector type stub. Chromium on Android implements this; the
 * TS lib doesn't ship the type yet. We just declare the bits we use. */
interface BarcodeDetectorLike {
  detect: (source: HTMLVideoElement) => Promise<{ rawValue: string; format: string }[]>;
}
interface BarcodeDetectorCtor {
  new (opts?: { formats?: string[] }): BarcodeDetectorLike;
  getSupportedFormats?: () => Promise<string[]>;
}
declare global {
  interface Window { BarcodeDetector?: BarcodeDetectorCtor }
}

interface Props {
  onScanned: (barcode: string) => void;
  onClose: () => void;
}

/**
 * Full-screen camera scanner. Opens the rear camera, runs BarcodeDetector
 * every animation frame, calls onScanned the first time a barcode resolves.
 *
 * Pixel 9 / Chromium Android supports BarcodeDetector natively. iOS Safari
 * is a maybe — we surface a clear message rather than try to ship a WASM
 * fallback (the user said Pixel-only).
 */
export function BarcodeScanner({ onScanned, onClose }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const rafRef = useRef<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hint, setHint] = useState<string>("starting camera...");

  useEffect(() => {
    if (!window.BarcodeDetector) {
      setError("This browser doesn't support barcode scanning. (Chrome on Android is required.)");
      return;
    }
    const detector = new window.BarcodeDetector({
      formats: ["ean_13", "ean_8", "upc_a", "upc_e", "code_128", "code_39", "qr_code"],
    });
    let cancelled = false;

    const start = async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: "environment" } },
          audio: false,
        });
        if (cancelled) {
          stream.getTracks().forEach(t => t.stop());
          return;
        }
        streamRef.current = stream;
        const v = videoRef.current;
        if (!v) return;
        v.srcObject = stream;
        await v.play();
        setHint("point at a barcode");
        scan(detector, v);
      } catch (e) {
        const msg = e instanceof Error ? e.message : "camera error";
        setError(`couldn't open camera: ${msg}`);
      }
    };

    const scan = (det: BarcodeDetectorLike, v: HTMLVideoElement) => {
      const tick = async () => {
        if (cancelled) return;
        try {
          const hits = await det.detect(v);
          if (hits.length > 0) {
            onScanned(hits[0].rawValue);
            return;
          }
        } catch {
          // BarcodeDetector throws transiently while frames are still loading;
          // we just keep going.
        }
        rafRef.current = requestAnimationFrame(() => { void tick(); });
      };
      void tick();
    };

    void start();

    return () => {
      cancelled = true;
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      streamRef.current?.getTracks().forEach(t => t.stop());
    };
  }, [onScanned]);

  return (
    <div className="fixed inset-0 z-50 bg-black/95 flex flex-col">
      <div className="flex items-center justify-between px-4 py-3 text-white">
        <span className="text-sm">{error ?? hint}</span>
        <button
          onClick={onClose}
          className="px-3 py-2 rounded bg-neutral-800 active:bg-neutral-600 text-sm min-h-[44px]"
        >
          cancel
        </button>
      </div>
      <div className="flex-1 relative">
        <video
          ref={videoRef}
          playsInline
          muted
          className="absolute inset-0 w-full h-full object-cover"
        />
        {/* Reticle */}
        <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
          <div className="w-72 h-44 border-2 border-emerald-400 rounded-lg" />
        </div>
      </div>
    </div>
  );
}
