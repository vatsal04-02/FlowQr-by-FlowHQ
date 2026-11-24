"use client";
import { CheckCircle2, FileText, Trash2, Upload, XCircle } from "lucide-react";
import Link from "next/link";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Skeleton } from "@/components/ui/Card";
import { Panel } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { API_V1 } from "@/lib/config";
import type { Asset, Overview, Readiness, SeoAssistant } from "@/lib/marketing";
import { useFetch } from "@/lib/use-api";

export function OverviewStrip({ o }: { o: Overview | null }) {
  const cells: [string, number | undefined, string][] = [["Campaigns", o?.campaigns, ""], ["Generated posts", o?.generated_posts, ""], ["Waiting for you", o?.awaiting_review, "text-warn"], ["Approved", o?.approved, ""],
    ["Scheduled", o?.scheduled, ""], ["Published", o?.published, "text-pos"], ["Failed", o?.failed, "text-neg"]];
  return (
    <ul aria-label="Campaign overview" className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
      {cells.map(([l, v, tone]) => (
        <li key={l} className="rounded-xl bg-surface-2 px-3 py-2.5"><span className="block text-[12px] text-muted">{l}</span><span className={`num text-xl font-semibold ${tone}`}>{v ?? "–"}</span></li>))}
    </ul>
  );
}

/** What FlowQR knows about whether it can publish for this business right now. It makes no Google call. */
export function ReadinessCard() {
  const r = useFetch<Readiness>("/marketing/readiness");
  if (r.loading && !r.data) return <Skeleton className="h-24" />;
  if (!r.data) return r.error ? <Alert tone="error">{r.error}</Alert> : null;
  const bad = r.data.checks.filter((c) => !c.ok);
  return (
    <Panel title="Publishing readiness" meta={r.data.can_publish ? "Ready" : "Not ready"}>
      <p className="text-[14px] text-ink-700">{r.data.statement} Every post still needs your approval first.</p>
      {bad.length > 0 && <ul className="mt-3 space-y-1.5">{bad.map((c) => (
        <li key={c.key} className="flex items-start gap-2 text-[13px]"><XCircle aria-hidden className="mt-0.5 h-4 w-4 shrink-0 text-neg" /><span><b className="font-semibold">{c.label}.</b> {c.detail}{c.action && <> <Link href={c.action} className="font-medium underline">Fix this</Link></>}</span></li>))}</ul>}
      {bad.length === 0 && <p className="mt-2 flex items-center gap-1.5 text-[13px] text-pos"><CheckCircle2 aria-hidden className="h-4 w-4" />Connection, permission and location all check out.</p>}
    </Panel>
  );
}

export function SeoPanel({ gid }: { gid: string }) {
  const s = useFetch<SeoAssistant>("/marketing/seo-assistant", { google_location_id: gid });
  if (s.loading && !s.data) return <Skeleton className="h-32" />;
  if (!s.data) return s.error ? <Alert tone="error">{s.error}</Alert> : null;
  const d = s.data;
  return (
    <Panel title="Local search ideas" meta={d.city ?? "Add your city"}>
      {d.repetition && <p className="mb-3 rounded-inner bg-warn-tint px-3 py-2 text-[13px] text-warn">{d.repetition}</p>}
      <p className="text-[13px] font-semibold text-ink-700">Phrases local customers may search</p>
      <ul className="mt-1.5 flex flex-wrap gap-1.5">{d.keywords.map((k) => <li key={k} className="rounded-full bg-surface-2 px-2.5 py-1 text-[13px]">{k}</li>)}{d.keywords.length === 0 && <li className="text-[13px] text-muted">Add your services to your Business brain to see phrases.</li>}</ul>
      <p className="mt-3 text-[13px] font-semibold text-ink-700">Topics that suit your business</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-5 text-[13px] text-ink-700">{d.topics.map((t) => <li key={t}>{t}</li>)}</ul>
      {d.missing.length > 0 && <>
        <p className="mt-3 text-[13px] font-semibold text-ink-700">Missing information</p>
        <ul className="mt-1 space-y-1 text-[13px] text-ink-700">{d.missing.slice(0, 5).map((m) => <li key={m.field}><b className="font-medium">{m.question}</b> <span className="text-muted">{m.why}</span></li>)}</ul>
        <Link href="/ai/studio/brand" className="mt-2 inline-block text-[13px] font-medium underline">Update your Business brain</Link></>}
      <p className="mt-3 text-[12px] text-muted">{d.note}</p>
    </Panel>
  );
}

const size = (n: number) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

/** The media library. `pick` turns it into a chooser: images can be selected (campaign context or one post's photo). */
export function Library({ picked, onPick, kind = "all", compact }: { picked?: string[]; onPick?: (id: string) => void; kind?: "all" | "image"; compact?: boolean }) {
  const toast = useToast();
  const { isAdmin } = useAuth();
  const lib = useFetch<{ assets: Asset[] }>("/marketing/assets");
  const file = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [notes, setNotes] = useState<string[]>([]);
  async function add(f: File) {
    setBusy(true); setErr(null); setNotes([]);
    const isDoc = /\.(pdf|docx|txt|md)$/i.test(f.name);
    try {
      const a = await api<Asset>("/marketing/assets", { method: "POST", raw: f, params: { kind: isDoc ? "document" : "image", file_name: f.name } });
      setNotes(a.warnings ?? []); toast("Added to your library."); void lib.reload();
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); if (file.current) file.current.value = ""; }
  }
  async function remove(a: Asset) {
    try { await api(`/marketing/assets/${a.id}`, { method: "DELETE" }); toast("Removed."); void lib.reload(); } catch (e) { setErr(errorMessage(e)); }
  }
  const items = (lib.data?.assets ?? []).filter((a) => kind === "all" || a.kind === kind);
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <input ref={file} type="file" className="sr-only" aria-label="Choose a file" accept={kind === "image" ? "image/jpeg,image/png" : "image/jpeg,image/png,.pdf,.docx,.txt,.md"} onChange={(e) => { const f = e.target.files?.[0]; if (f) void add(f); }} />
        <Button size="sm" variant="secondary" icon={<Upload className="h-4 w-4" />} loading={busy} onClick={() => file.current?.click()}>{kind === "image" ? "Upload a photo" : "Upload a photo or document"}</Button>
        <span className="text-[12px] text-muted">{kind === "image" ? "JPG or PNG, 10 KB to 5 MB, at least 250 px." : "JPG or PNG photos; PDF, Word or text catalogues up to 10 MB. Videos can't be attached to Google posts."}</span>
      </div>
      {err && <div className="mt-2"><Alert tone="error">{err}</Alert></div>}
      {notes.map((n) => <p key={n} className="mt-2 rounded-inner bg-warn-tint px-3 py-2 text-[13px] text-warn">{n}</p>)}
      {lib.loading && !lib.data ? <Skeleton className="mt-3 h-24" /> : items.length === 0 ? <p className="mt-3 rounded-tile bg-surface-2 p-4 text-sm text-muted">Nothing here yet. Upload product or shop photos and FlowQR can use them in your posts.</p> : (
        <ul className={`mt-3 grid gap-2 ${compact ? "grid-cols-3 sm:grid-cols-4" : "grid-cols-2 sm:grid-cols-3 lg:grid-cols-5"}`}>
          {items.map((a) => {
            const on = picked?.includes(a.id);
            return (
              <li key={a.id} className={`overflow-hidden rounded-xl border ${on ? "border-ink-solid ring-2 ring-ink-solid" : "border-ink-100"} bg-surface`}>
                <button type="button" disabled={!onPick || (a.kind === "document" && kind === "image")} onClick={() => onPick?.(a.id)} aria-pressed={on} aria-label={`${on ? "Selected: " : ""}${a.label || a.file_name || "file"}`} className="block w-full text-left">
                  {a.kind === "image" ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={`${API_V1}/marketing/assets/${a.id}/file`} alt={a.label || a.file_name || "Uploaded photo"} className="aspect-[4/3] w-full object-cover" loading="lazy" />
                  ) : <span className="grid aspect-[4/3] w-full place-items-center bg-surface-2"><FileText aria-hidden className="h-7 w-7 text-muted" /></span>}
                  <span className="block px-2 py-1.5"><span data-words="skip" className="block truncate text-[12px] font-medium">{a.label || a.file_name}</span>
                    <span className="block text-[11px] text-muted">{a.kind === "image" ? `${a.width}×${a.height} · ` : a.readable === false ? "Stored, not read · " : ""}{size(a.size_bytes)}</span></span>
                </button>
                {isAdmin && !onPick && <div className="px-2 pb-2"><button type="button" onClick={() => void remove(a)} className="inline-flex items-center gap-1 text-[12px] text-muted hover:text-neg"><Trash2 aria-hidden className="h-3.5 w-3.5" />Delete</button></div>}
              </li>);
          })}
        </ul>)}
    </div>
  );
}

export function LibraryPanel() {
  return <Panel title="Media library" meta="Reuse these in any campaign"><Library /></Panel>;
}
