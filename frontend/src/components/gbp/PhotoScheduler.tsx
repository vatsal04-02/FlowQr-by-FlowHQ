"use client";
import { API_V1 } from "@/lib/config";
import clsx from "clsx";
import { Check, Clock, ImagePlus, Loader2, RefreshCw, Upload, X } from "lucide-react";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Skeleton } from "@/components/ui/Card";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, timeAgo } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

interface Item {
  id: string; category: string; category_label: string; description: string | null; file_name: string | null; width: number; height: number; size_bytes: number;
  status: "awaiting_approval" | "scheduled" | "publishing" | "published" | "failed" | "canceled"; stage: string; scheduled_for: string | null; next_attempt_at: string | null;
  attempts: number; failure_reason: string | null; google_url: string | null; google_checked_at: string | null; published_at: string | null; warnings?: string[];
}
interface Library { items: Item[]; categories: Record<string, string>; timezone: string; rules: { min_bytes: number; max_bytes: number; min_edge: number; recommended_edge: number } }
interface Coverage { on_google: Record<string, number>; total_on_google: number; suggestions: { category: string; label: string; on_google: boolean; pending: boolean }[]; note: string }

const tone = (s: Item["status"], live: boolean) =>
  s === "published" ? (live ? "bg-pos-tint text-pos" : "bg-warn-tint text-warn") : s === "failed" ? "bg-neg-tint text-neg" : s === "awaiting_approval" ? "bg-accent-tint text-accent-ink" : "bg-surface-2 text-ink-700";

/** Read the picked file's pixel size in the browser, so obvious problems are explained before anything is uploaded. */
function dims(file: File): Promise<{ w: number; h: number } | null> {
  return new Promise((res) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => { res({ w: img.naturalWidth, h: img.naturalHeight }); URL.revokeObjectURL(url); };
    img.onerror = () => { res(null); URL.revokeObjectURL(url); };
    img.src = url;
  });
}

/**
 * Photo Manager & Scheduler: which photo types Google already shows (read from Google), upload into FlowQR's library with Google's rules
 * checked up front, owner approval with a date and time, and each photo's real progress: waiting, scheduled, sending, Google processing,
 * live on Google, or failed with Google's reason. Uploading here never counts as "on Google".
 */
export function PhotoScheduler({ gid }: { gid: string }) {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const lib = useFetch<Library>(`/gbp/${gid}/library`);
  const cov = useFetch<Coverage>(`/gbp/${gid}/library/coverage`);
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [size, setSize] = useState<{ w: number; h: number } | null>(null);
  const [category, setCategory] = useState("EXTERIOR");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [when, setWhen] = useState<Record<string, string>>({});
  const input = useRef<HTMLInputElement>(null);
  const reload = () => { void lib.reload(); void cov.reload(); };

  async function pick(f: File | null) {
    setErr(null); setFile(f); setPreview(f ? URL.createObjectURL(f) : null); setSize(f ? await dims(f) : null);
  }
  const rules = lib.data?.rules;
  const problem = !file || !rules ? null
    : !["image/jpeg", "image/png"].includes(file.type) ? "Google accepts JPG or PNG photos."
    : file.size > rules.max_bytes ? `This file is ${(file.size / 1048576).toFixed(1)} MB. Google accepts up to 5 MB.`
    : file.size < rules.min_bytes ? "This file is under 10 KB. Use a real photo."
    : size && !["COVER", "PROFILE"].includes(category) && Math.min(size.w, size.h) < rules.min_edge ? `This photo is ${size.w}×${size.h} px. Google needs at least 250 px on each side.` : null;

  async function send() {
    if (!file || problem) return;
    setBusy("upload"); setErr(null);
    try {
      const out = await api<Item>(`/gbp/${gid}/library`, { method: "POST", raw: file, params: { category, description: description || undefined, file_name: file.name } });
      toast(isAdmin ? "Added. Approve it below to send it to Google." : "Added. An owner or admin approves photos before they go to Google.");
      (out.warnings ?? []).forEach((w) => toast(w));
      setFile(null); setPreview(null); setSize(null); setDescription(""); if (input.current) input.current.value = "";
      reload();
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(null); }
  }
  async function act(id: string, path: string, body?: unknown, ok?: string) {
    setBusy(id + path);
    try { await api(`/gbp/${gid}/library/${id}/${path}`, { method: "POST", body: body ?? {} }); if (ok) toast(ok); reload(); }
    catch (e) { toast(e instanceof ApiError ? errorMessage(e) : "Something went wrong.", "error"); } finally { setBusy(null); }
  }

  const items = lib.data?.items ?? [];
  const cats = lib.data?.categories ?? {};
  return (
    <div className="space-y-6">
      <section className="panel p-5 sm:p-6" aria-labelledby="cov-h">
        <div className="flex flex-wrap items-baseline justify-between gap-2"><h2 id="cov-h" className="text-lg font-semibold">Photo types on Google</h2>
          {cov.data && <span className="text-[13px] text-muted">{cov.data.total_on_google} photos on Google now</span>}</div>
        {cov.error ? <p className="mt-3 text-sm text-muted">Couldn&rsquo;t read your photos from Google just now. {cov.error}</p> : !cov.data ? <Skeleton className="mt-4 h-20" /> : (
          <>
            <ul className="mt-4 grid grid-cols-2 gap-2.5 sm:grid-cols-4 lg:grid-cols-7">
              {cov.data.suggestions.map((s) => (
                <li key={s.category}>
                  <button type="button" onClick={() => setCategory(s.category)} className={clsx("flex w-full flex-col items-start gap-1.5 rounded-tile p-3 text-left transition-colors",
                    s.on_google ? "bg-pos-tint" : s.pending ? "bg-surface-2" : "bg-accent-tint ring-1 ring-inset ring-accent-edge hover:bg-brand-100", category === s.category && "outline outline-2 outline-accent")}>
                    <span className={clsx("grid h-7 w-7 place-items-center rounded-full", s.on_google ? "bg-pos text-pure-white dark:text-pure-ink" : "bg-surface")}>
                      {s.on_google ? <Check className="h-4 w-4" strokeWidth={2.5} aria-hidden /> : s.pending ? <Clock className="h-4 w-4 text-muted" aria-hidden /> : <ImagePlus className="h-4 w-4 text-accent-ink" aria-hidden />}
                    </span>
                    <span className="text-sm font-semibold leading-tight">{s.label}</span>
                    <span className="text-xs text-muted">{s.on_google ? `${cov.data!.on_google[s.category]} on Google` : s.pending ? "On its way" : "Missing: add one"}</span>
                  </button>
                </li>
              ))}
            </ul>
            <p className="mt-3 text-xs text-muted">{cov.data.note}</p>
          </>
        )}
      </section>

      <section className="panel p-5 sm:p-6" aria-labelledby="up-h">
        <h2 id="up-h" className="text-lg font-semibold">Add a photo</h2>
        <p className="mt-0.5 text-sm text-muted">JPG or PNG, 10 KB to 5 MB, at least 250×250 px (720×720 recommended). Real, well-lit photos without heavy filters.</p>
        <div className="mt-4 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <label onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); void pick(e.dataTransfer.files[0] ?? null); }}
            className="hatch relative grid min-h-[220px] cursor-pointer place-items-center overflow-hidden rounded-tile bg-surface-2 text-center">
            <input ref={input} type="file" accept="image/jpeg,image/png" className="sr-only" onChange={(e) => void pick(e.target.files?.[0] ?? null)} />
            {/* eslint-disable-next-line @next/next/no-img-element */}
            {preview ? <img src={preview} alt="Selected photo" className="absolute inset-0 h-full w-full object-cover" />
              : <span className="flex flex-col items-center gap-2 p-6"><span className="grid h-12 w-12 place-items-center rounded-full bg-surface"><Upload className="h-5 w-5" aria-hidden /></span>
                  <span className="font-semibold">Drop a photo here or choose one</span><span className="text-xs text-muted">Stays in FlowQR until it&rsquo;s approved</span></span>}
          </label>
          <div className="space-y-4">
            <div>
              <p className="mb-1.5 text-sm font-medium">Photo type</p>
              <div role="radiogroup" aria-label="Photo type" className="flex flex-wrap gap-1.5">
                {Object.entries(cats).map(([k, l]) => (
                  <button key={k} type="button" role="radio" aria-checked={category === k} onClick={() => setCategory(k)}
                    className={clsx("min-h-9 rounded-full px-3.5 text-[13px] font-medium transition-colors", category === k ? "bg-ink-solid text-ink-on" : "bg-surface-2 text-ink hover:bg-surface-3")}>{l}</button>
                ))}
              </div>
            </div>
            {!["COVER", "PROFILE"].includes(category) && (
              <label className="block"><span className="mb-1.5 block text-sm font-medium">Caption (optional)</span>
                <input value={description} maxLength={300} onChange={(e) => setDescription(e.target.value)} placeholder="e.g. Our physiotherapy room"
                  className="min-h-11 w-full rounded-inner bg-surface-2 px-4 text-sm" /></label>
            )}
            {file && <p className="text-[13px] text-muted">{file.name} · {(file.size / 1024).toFixed(0)} KB{size ? ` · ${size.w}×${size.h} px` : ""}</p>}
            {problem && <Alert tone="warning">{problem}</Alert>}
            {err && <Alert tone="error">{err}</Alert>}
            <Button icon={<Upload className="h-4 w-4" />} disabled={!file || !!problem} loading={busy === "upload"} onClick={() => void send()}>Add to library</Button>
          </div>
        </div>
      </section>

      <section className="panel p-5 sm:p-6" aria-labelledby="q-h">
        <h2 id="q-h" className="text-lg font-semibold">Photo queue</h2>
        <p className="mt-0.5 text-sm text-muted">&ldquo;Live on Google&rdquo; appears only when Google itself serves the photo. Google can take 24–48 hours, and shows photos only once the profile is verified.</p>
        {lib.loading && !lib.data ? <Skeleton className="mt-4 h-40" /> : items.length === 0 ? <p className="mt-4 rounded-tile bg-surface-2 p-5 text-sm text-muted">No photos in the library yet.</p> : (
          <ul className="mt-4 grid gap-3.5 sm:grid-cols-2 xl:grid-cols-3">
            {items.map((m) => {
              const live = !!m.google_url;
              return (
                <li key={m.id} className="overflow-hidden rounded-tile bg-surface-2">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={`${API_V1}/gbp/${gid}/library/${m.id}/image`} alt={m.description ?? m.category_label} loading="lazy" className="aspect-[4/3] w-full bg-surface-3 object-cover" />
                  <div className="space-y-2 p-4">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-sm font-semibold">{m.category_label}</span>
                      <span className={clsx("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium", tone(m.status, live))}>
                        {m.status === "publishing" && <Loader2 className="h-3 w-3 fq-spin" aria-hidden />}{m.stage}</span>
                    </div>
                    <p className="text-xs text-muted">{m.width}×{m.height} px · {(m.size_bytes / 1024).toFixed(0)} KB
                      {m.status === "scheduled" && m.scheduled_for ? ` · goes ${new Date(m.scheduled_for) > new Date() ? fmtDate(m.scheduled_for, { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "within a minute"}` : ""}
                      {m.published_at ? ` · accepted by Google ${timeAgo(m.published_at)}` : ""}</p>
                    {m.failure_reason && <p className={clsx("text-[13px]", m.status === "failed" ? "text-neg" : "text-warn")}>{m.failure_reason}</p>}
                    {isAdmin && m.status === "awaiting_approval" && (
                      <div className="flex flex-wrap items-center gap-2 pt-1">
                        <input type="datetime-local" aria-label="Send to Google at" value={when[m.id] ?? ""} onChange={(e) => setWhen({ ...when, [m.id]: e.target.value })}
                          className="min-h-9 rounded-full bg-surface px-3 text-[13px]" />
                        <Button size="sm" loading={busy === m.id + "approve"} onClick={() => void act(m.id, "approve", { scheduled_for: when[m.id] || null }, when[m.id] ? "Scheduled." : "Approved: it goes to Google within a minute.")}>
                          {when[m.id] ? "Approve & schedule" : "Approve now"}</Button>
                        <button type="button" aria-label="Remove from queue" onClick={() => void act(m.id, "cancel", undefined, "Removed.")} className="grid h-9 w-9 place-items-center rounded-full text-muted hover:bg-surface-3"><X className="h-4 w-4" /></button>
                      </div>
                    )}
                    {isAdmin && m.status === "scheduled" && <button type="button" onClick={() => void act(m.id, "cancel", undefined, "Cancelled.")} className="text-[13px] font-semibold text-muted hover:text-neg">Cancel</button>}
                    {isAdmin && m.status === "failed" && <Button size="sm" variant="secondary" icon={<RefreshCw className="h-4 w-4" />} loading={busy === m.id + "retry"} onClick={() => void act(m.id, "retry", undefined, "Will try again within a minute.")}>Retry</Button>}
                    {m.status === "published" && !live && <button type="button" onClick={() => void act(m.id, "check")} className="text-[13px] font-semibold text-accent-ink hover:underline">Ask Google again</button>}
                    {!isAdmin && m.status === "awaiting_approval" && <p className="text-xs text-muted">An owner or admin approves photos.</p>}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
