"use client";
import { useEffect, useRef, useState } from "react";
import { apiFile } from "@/lib/api";
import { DEVICES, type Device } from "@/lib/website";

/** The builder's own rendering of the draft, in a sandboxed frame (no scripts), at a real device width scaled to fit. It is fetched again only when `version` changes. */
export function Preview({ version, device, ready }: { version: string; device: Device; ready: boolean }) {
  const [html, setHtml] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ w: 0, h: 0 });

  useEffect(() => {
    if (!ready) return;
    let live = true;
    apiFile("/website/preview").then(async ({ blob }) => { const t = await blob.text(); if (live) { setHtml(t); setError(false); } }).catch(() => live && setError(true));
    return () => { live = false; };
  }, [version, ready]);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const width = DEVICES[device];
  const scale = size.w ? Math.min(1, size.w / width) : 1;
  return (
    <div ref={box} className="relative h-full min-h-[420px] w-full overflow-hidden rounded-[18px] bg-surface-2">
      {html ? (
        <div className="absolute inset-0">
          <iframe title="Preview of your website" sandbox="" srcDoc={html} className="absolute top-0 origin-top-left border-0 bg-white"
          style={{ width, height: size.h / scale || 600, transform: `scale(${scale})`, left: Math.max(0, (size.w - width * scale) / 2) }} />
        </div>
      ) : (
        <div className="grid h-full place-items-center p-6 text-center">
          <div className="w-full max-w-sm space-y-3" aria-hidden>
            <div className="h-6 w-2/3 rounded-lg bg-white/80" /><div className="h-28 rounded-xl bg-white/80" /><div className="h-4 w-5/6 rounded bg-white/70" /><div className="h-4 w-3/4 rounded bg-white/70" />
          </div>
          <p className="mt-4 text-[13px] text-muted">{error ? "The preview could not be loaded." : "Your website appears here as soon as the first section is built."}</p>
        </div>
      )}
    </div>
  );
}
