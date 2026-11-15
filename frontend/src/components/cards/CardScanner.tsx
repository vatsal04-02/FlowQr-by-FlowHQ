"use client";
import jsQR from "jsqr";
import { Camera, CameraOff, Keyboard, Loader2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";

type Phase = "starting" | "scanning" | "denied" | "nocamera" | "insecure" | "error";

interface Detector { detect(source: CanvasImageSource): Promise<{ rawValue: string }[]> }
type DetectorCtor = new (opts: { formats: string[] }) => Detector;

/**
 * Reads a card's QR code with the device camera. Uses the browser's own barcode detector where there is one (Chrome and most Android
 * browsers) and falls back to jsQR on video frames everywhere else (iPhone Safari, desktop Firefox). Nothing is recorded or uploaded:
 * the camera stream stays in this page and is stopped the moment a code is read, or when this component goes away.
 *
 * `onResult` receives exactly what was read (a link, a token, anything). The server decides whether it is a card.
 */
export function CardScanner({ onResult, onClose, busy = false }: { onResult: (text: string) => void; onClose: () => void; busy?: boolean }) {
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const done = useRef(false);
  const [phase, setPhase] = useState<Phase>("starting");
  const [manual, setManual] = useState("");

  const stop = useCallback(() => {
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
  }, []);

  useEffect(() => {
    let raf = 0;
    let cancelled = false;
    const canvas = document.createElement("canvas");
    const ctx = canvas.getContext("2d", { willReadFrequently: true });

    async function start() {
      if (!window.isSecureContext) { setPhase("insecure"); return; }
      if (!navigator.mediaDevices?.getUserMedia) { setPhase("nocamera"); return; }
      try {
        const s = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 } }, audio: false });
        if (cancelled) { s.getTracks().forEach((t) => t.stop()); return; }
        stream.current = s;
        const v = video.current;
        if (!v) return;
        v.srcObject = s;
        await v.play().catch(() => undefined);
        setPhase("scanning");
        const Native = (window as unknown as { BarcodeDetector?: DetectorCtor }).BarcodeDetector;
        const detector = Native ? new Native({ formats: ["qr_code"] }) : null;
        let last = 0;
        let n = 0;
        // jsQR is sensitive to how big the code appears: it can read a code at one size and miss it at the next. Each look uses a
        // different frame size, so a code held still is read within a fraction of a second whichever size suits it.
        const widths = [960, 720, 540, 400, 300];
        const tick = async (now: number) => {
          if (cancelled || done.current) return;
          raf = requestAnimationFrame(tick);
          if (now - last < 120 || v.readyState < 2 || !v.videoWidth) return; // about 8 looks a second is plenty and keeps phones cool
          last = now;
          let text: string | null = null;
          try {
            if (detector) text = (await detector.detect(v))[0]?.rawValue ?? null;
            if (!text && ctx) {
              const w = Math.min(widths[n++ % widths.length], v.videoWidth), h = Math.round((v.videoHeight / v.videoWidth) * w);
              canvas.width = w; canvas.height = h;
              ctx.drawImage(v, 0, 0, w, h);
              text = jsQR(ctx.getImageData(0, 0, w, h).data, w, h, { inversionAttempts: "dontInvert" })?.data ?? null;
            }
          } catch { /* a frame that cannot be read is just skipped */ }
          if (text && !done.current) { done.current = true; stop(); onResult(text); }
        };
        raf = requestAnimationFrame(tick);
      } catch (e) {
        const name = (e as DOMException)?.name;
        setPhase(name === "NotAllowedError" || name === "SecurityError" ? "denied" : name === "NotFoundError" || name === "OverconstrainedError" ? "nocamera" : "error");
      }
    }
    void start();
    return () => { cancelled = true; cancelAnimationFrame(raf); stop(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const problem = {
    denied: "Camera access was blocked. Allow the camera for this site in your browser settings, or type the serial number below.",
    nocamera: "No camera was found on this device. Type the serial number printed on the card below.",
    insecure: "The camera only works on a secure (https) page. Type the serial number printed on the card below.",
    error: "The camera could not be started. Type the serial number printed on the card below.",
  }[phase as "denied" | "nocamera" | "insecure" | "error"];

  return (
    <div className="space-y-3" data-testid="card-scanner">
      {!problem && (
        <div className="relative overflow-hidden rounded-xl bg-ink-900">
          <video ref={video} muted playsInline aria-label="Camera view: point it at the QR code on the card" className="aspect-[4/3] w-full object-cover" />
          <div className="pointer-events-none absolute inset-0 grid place-items-center" aria-hidden>
            <div className="h-1/2 w-1/2 rounded-2xl border-2 border-white/80 shadow-[0_0_0_999px_rgba(0,0,0,.35)]" />
          </div>
          <p role="status" className="absolute inset-x-0 bottom-0 bg-black/55 px-3 py-2 text-center text-sm text-white">
            {busy ? <span className="inline-flex items-center gap-2"><Loader2 className="h-4 w-4 fq-spin" aria-hidden />Looking up the card…</span>
              : phase === "starting" ? "Starting the camera…" : <span className="inline-flex items-center gap-2"><Camera className="h-4 w-4" aria-hidden />Point the camera at the QR code on the card</span>}
          </p>
        </div>
      )}
      {problem && <p role="alert" className="flex gap-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-900"><CameraOff className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />{problem}</p>}
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); const v = manual.trim(); if (v) { done.current = true; stop(); onResult(v); } }}>
        <label className="sr-only" htmlFor="card-manual">Card serial number</label>
        <div className="relative flex-1">
          <Keyboard className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden />
          <input id="card-manual" value={manual} onChange={(e) => setManual(e.target.value)} placeholder="Or type the serial, e.g. FQR-0012" autoCapitalize="characters" autoComplete="off" spellCheck={false}
            className="min-h-11 w-full rounded-xl border border-ink-200 pl-9 pr-3 text-[16px] uppercase placeholder:normal-case" />
        </div>
        <Button type="submit" variant="secondary" disabled={!manual.trim() || busy}>Look up</Button>
      </form>
      <div className="flex justify-end"><Button variant="ghost" size="sm" icon={<X className="h-4 w-4" />} onClick={() => { done.current = true; stop(); onClose(); }}>Stop scanning</Button></div>
    </div>
  );
}
