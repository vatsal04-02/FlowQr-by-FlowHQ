"use client";
import { CheckCircle2, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Alert, Skeleton } from "@/components/ui/Card";
import { Input, Select } from "@/components/ui/Form";
import { ApiError, apiFile, errorMessage } from "@/lib/api";
import type { QRStyle } from "@/lib/types";

const HEX = /^#[0-9A-Fa-f]{6}$/;
const MIN_CONTRAST = 4.5; // same rule the server enforces (backend/app/services/qr_style.py)

function luminance(hex: string): number {
  const lin = (c: number) => { const v = c / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  const n = parseInt(hex.slice(1), 16);
  return 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255);
}

/** Why the server would refuse this style, in the user's terms; null if it passes the colour rules. */
export function styleProblem(s: QRStyle): string | null {
  if (!HEX.test(s.dark) || !HEX.test(s.light)) return "Colours must be 6-digit hex values such as #1B46B8.";
  const d = luminance(s.dark), l = luminance(s.light);
  if (d >= l) return "The code colour must be darker than the background. Light-on-dark codes fail on many scanners.";
  const ratio = (l + 0.05) / (d + 0.05);
  if (ratio < MIN_CONTRAST) return `These colours are too close (contrast ${ratio.toFixed(1)}:1, need at least ${MIN_CONTRAST}:1). Pick a darker code colour or a lighter background.`;
  if (s.caption && /[^ -ÿ]/.test(s.caption)) return "The caption can use Latin letters, digits and punctuation only for now.";
  return null;
}

function Colour({ label, value, onChange, disabled }: { label: string; value: string; onChange: (v: string) => void; disabled?: boolean }) {
  return (
    <div>
      <p className="mb-1 text-[13px] font-medium text-ink-700">{label}</p>
      <div className="flex items-center gap-2">
        <input type="color" aria-label={`${label} picker`} disabled={disabled} value={HEX.test(value) ? value : "#000000"} onChange={(e) => onChange(e.target.value.toUpperCase())}
          className="h-11 w-12 cursor-pointer rounded-lg border border-ink-300 bg-white p-1 disabled:cursor-not-allowed sm:h-9" />
        <input aria-label={`${label} hex value`} disabled={disabled} value={value} maxLength={7} onChange={(e) => onChange(e.target.value.trim().toUpperCase())}
          className="min-h-11 w-28 rounded-lg border border-ink-300 bg-white px-2 font-mono text-sm disabled:bg-ink-50 sm:min-h-9" />
      </div>
    </div>
  );
}

/** Controlled editor for a QR style. The parent owns the value and decides when to save. */
export function QrStyleEditor({ value, onChange, hasLogo, disabled }: { value: QRStyle; onChange: (v: QRStyle) => void; hasLogo: boolean; disabled?: boolean }) {
  const set = <K extends keyof QRStyle>(k: K, v: QRStyle[K]) => onChange({ ...value, [k]: v });
  const logoOn = value.use_logo && hasLogo;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap gap-5">
        <Colour label="Code colour" value={value.dark} onChange={(v) => set("dark", v)} disabled={disabled} />
        <Colour label="Background" value={value.light} onChange={(v) => set("light", v)} disabled={disabled} />
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block text-[13px] font-medium text-ink-700">Margin around the code: {value.margin} modules
          <input type="range" min={4} max={16} step={1} disabled={disabled} value={value.margin} onChange={(e) => set("margin", Number(e.target.value))} className="mt-2 block w-full" />
          <span className="mt-1 block text-xs font-normal text-ink-500">4 is the minimum a QR code needs. It can&rsquo;t go lower.</span>
        </label>
        <Select label="Download size" disabled={disabled} value={String(value.size_px)} onChange={(e) => set("size_px", Number(e.target.value))}
          hint="Minimum width of PNG and SVG files. PDFs are vector and print sharp at any size.">
          {[512, 1024, 2048, 4096].map((n) => <option key={n} value={n}>{n} px</option>)}
        </Select>
        <Select label="Error correction" disabled={disabled || logoOn} value={logoOn ? "H" : value.error_correction} onChange={(e) => set("error_correction", e.target.value as QRStyle["error_correction"])}
          hint={logoOn ? "Fixed at High while a logo covers part of the code." : "Higher survives more scratches and dirt; lower makes a slightly simpler code."}>
          <option value="L">Low (7%)</option><option value="M">Medium (15%)</option><option value="Q">Quartile (25%)</option><option value="H">High (30%)</option>
        </Select>
        <Input label="Caption under the code (optional)" maxLength={60} disabled={disabled} value={value.caption ?? ""} onChange={(e) => set("caption", e.target.value || null)}
          hint="Latin letters, digits and punctuation only for now." />
      </div>
      <div className="rounded-lg border border-ink-100 p-3">
        <label className="flex min-h-11 items-center gap-2 text-sm font-medium sm:min-h-0">
          <input type="checkbox" className="h-[18px] w-[18px]" disabled={disabled || !hasLogo} checked={logoOn} onChange={(e) => set("use_logo", e.target.checked)} />
          Put the logo in the middle of the code
        </label>
        {!hasLogo && <p className="mt-1 text-xs text-ink-500">Upload a logo first.</p>}
        {logoOn && (
          <label className="mt-3 block text-[13px] font-medium text-ink-700">Logo size: {Math.round(value.logo_scale * 100)}% of the code width
            <input type="range" min={10} max={25} step={1} disabled={disabled} value={Math.round(value.logo_scale * 100)} onChange={(e) => set("logo_scale", Number(e.target.value) / 100)} className="mt-2 block w-full" />
            <span className="mt-1 block text-xs font-normal text-ink-500">25% is the largest allowed; bigger logos hide too much of the code.</span>
          </label>)}
      </div>
    </div>
  );
}

/** Live sample drawn by the server with this style, with the server's own scan check. Never a real card or campaign code. */
export function QrPreview({ value, version = 0 }: { value: QRStyle; version?: number }) {
  const [url, setUrl] = useState<string | null>(null);
  const [scan, setScan] = useState<"yes" | "no" | "unverified" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const last = useRef<string | null>(null);
  const problem = styleProblem(value);
  const key = JSON.stringify(value) + version;

  useEffect(() => {
    if (problem) { setLoading(false); return; }
    const ctl = new AbortController();
    setLoading(true);
    const t = setTimeout(async () => {
      try {
        const { blob, headers } = await apiFile("/qr/preview.png", { method: "POST", body: value, signal: ctl.signal });
        const next = URL.createObjectURL(blob);
        if (last.current) URL.revokeObjectURL(last.current);
        last.current = next;
        setUrl(next); setScan((headers.get("X-FlowQR-Scannable") as "yes" | "no" | "unverified" | null) ?? "unverified"); setError(null);
      } catch (e) {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setError(e instanceof ApiError && e.status === 429 ? "Too many previews. Wait a moment, then change something to refresh." : errorMessage(e));
      } finally { if (!ctl.signal.aborted) setLoading(false); }
    }, 450);
    return () => { clearTimeout(t); ctl.abort(); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, problem]);
  useEffect(() => () => { if (last.current) URL.revokeObjectURL(last.current); }, []);

  return (
    <div className="space-y-2">
      <div className="keep-light mx-auto grid aspect-square w-full max-w-[260px] place-items-center rounded-inner bg-white p-2">
        {problem ? <p className="px-3 text-center text-sm text-ink-500">Fix the colours to see a preview.</p>
          : !url && loading ? <Skeleton className="h-full w-full" />
          /* eslint-disable-next-line @next/next/no-img-element */
          : url ? <img src={url} alt="Sample QR code drawn with this design" className={`h-full w-full object-contain ${loading ? "opacity-50" : ""}`} /> : null}
      </div>
      <p className="text-center text-xs text-ink-500">Sample only. It doesn&rsquo;t open any of your cards or campaigns.</p>
      {problem ? <Alert tone="warning" title="This design wouldn't scan reliably">{problem}</Alert>
        : error ? <Alert tone="error" title="Couldn't draw the preview">{error}</Alert>
        : scan === "yes" ? <p className="flex items-center justify-center gap-1.5 text-[13px] font-medium text-green-700"><CheckCircle2 className="h-4 w-4" aria-hidden />Scan check passed</p>
        : scan === "no" ? <p className="flex items-center justify-center gap-1.5 text-[13px] font-medium text-red-700"><TriangleAlert className="h-4 w-4" aria-hidden />Scan check failed. This design can&rsquo;t be saved.</p>
        : scan === "unverified" ? <p className="text-center text-[13px] text-ink-500">Colour rules pass. The server&rsquo;s scan check isn&rsquo;t available right now.</p> : null}
    </div>
  );
}
