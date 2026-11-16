"use client";
import clsx from "clsx";
import { Camera, Check, ExternalLink, ImagePlus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Skeleton } from "@/components/ui/Card";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import { Gate } from "./tools";

interface Media { name: string; category: string | null; url: string | null; thumbnail: string | null; created_at?: string | null }

/** The photo types Google profiles are expected to have, in plain words. Used for the filter and the "what's missing" checklist. */
const KINDS: [string, string][] = [
  ["COVER", "Cover"], ["PROFILE", "Profile"], ["LOGO", "Logo"], ["EXTERIOR", "Outside"], ["INTERIOR", "Inside"], ["AT_WORK", "At work"], ["TEAMS", "Team"], ["PRODUCT", "Products"], ["ADDITIONAL", "Other"],
];
const NEEDED = ["COVER", "LOGO", "EXTERIOR", "INTERIOR"] as const;
const label = (c: string | null) => KINDS.find(([k]) => k === c)?.[1] ?? (c ? c.replace(/_/g, " ").toLowerCase() : "Photo");

/**
 * A photo that never shows a broken-image icon: it tries the thumbnail, then the full image (without sending a referrer, which some
 * Google image hosts reject), and if both fail it shows a clear "preview unavailable" tile with the photo's type.
 */
export function SafeImage({ m, className }: { m: Pick<Media, "thumbnail" | "url" | "category">; className?: string }) {
  const sources = [m.thumbnail, m.url].filter((x): x is string => !!x);
  const [i, setI] = useState(0);
  if (i >= sources.length) {
    return (
      <div className={clsx("grid place-items-center bg-brand-50 text-center", className)}>
        <div className="px-2"><Camera className="mx-auto h-6 w-6 text-brand-700" strokeWidth={1.5} aria-hidden /><p className="mt-1.5 text-[13px] font-medium text-navy">{label(m.category)} photo</p><p className="text-xs text-ink-500">Preview not available</p></div>
      </div>
    );
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img key={sources[i]} src={sources[i]} alt={`${label(m.category)} photo on your Google profile`} loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={() => setI((n) => n + 1)} className={className} />;
}

/** `canAdd=false` hides the add-by-link form (the Photos page uses the library and scheduler for adding, so every photo is approved first). */
export function Gallery({ gid, canAdd = true }: { gid: string; canAdd?: boolean }) {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useFetch<Media[]>(`/gbp/${gid}/media`);
  const [url, setUrl] = useState(""); const [cat, setCat] = useState("ADDITIONAL"); const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("ALL");
  const [open, setOpen] = useState<Media | null>(null);
  const [previewOk, setPreviewOk] = useState<boolean | null>(null);
  const counts = useMemo(() => { const c: Record<string, number> = {}; for (const m of data ?? []) c[m.category ?? "ADDITIONAL"] = (c[m.category ?? "ADDITIONAL"] ?? 0) + 1; return c; }, [data]);
  if (error) return <Gate error={error} />;
  const shown = (data ?? []).filter((m) => filter === "ALL" || (m.category ?? "ADDITIONAL") === filter);
  const valid = url.startsWith("https://");
  const missing = NEEDED.filter((k) => !counts[k]);

  async function add() {
    setBusy(true);
    try { await api(`/gbp/${gid}/media`, { method: "POST", body: { source_url: url, category: cat } }); toast("Photo sent to Google."); setUrl(""); setPreviewOk(null); await reload(); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); }
  }
  async function remove(m: Media) {
    if (!confirm("Delete this photo from Google?")) return;
    try { await api(`/gbp/${gid}/media`, { method: "DELETE", params: { name: m.name } }); toast("Photo deleted."); setOpen(null); void reload(); }
    catch (e) { toast(errorMessage(e), "error"); }
  }

  return (
    <div className="space-y-5">
      {/* what a complete photo set looks like, from the real counts */}
      <section aria-label="Photo checklist" className="rounded-2xl bg-brand-50 p-4 sm:p-5">
        <div className="flex flex-wrap items-end justify-between gap-2">
          <div><h2 className="text-base font-bold text-navy">{loading && !data ? "Checking your photos…" : `${data?.length ?? 0} photos on Google`}</h2>
            <p className="text-sm text-ink-700">{missing.length === 0 ? "You have every key photo type. Fresh photos keep your profile active." : `Add ${missing.map((k) => label(k).toLowerCase()).join(", ")} to look complete.`}</p></div>
        </div>
        <ul className="mt-3 flex flex-wrap gap-2">
          {NEEDED.map((k) => (
            <li key={k} className={clsx("inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-[13px] font-semibold", counts[k] ? "bg-white text-green-800" : "bg-white/60 text-ink-500")}>
              {counts[k] ? <Check className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden /> : <span aria-hidden className="h-2 w-2 rounded-full bg-ink-300" />}{label(k)}<span className="sr-only">{counts[k] ? " (added)" : " (missing)"}</span>
            </li>))}
        </ul>
      </section>

      {isAdmin && canAdd && (
        <section aria-labelledby="add-photo-h" className="rounded-2xl border border-ink-100 bg-white p-4 sm:p-5">
          <h2 id="add-photo-h" className="text-base font-bold text-navy">Add a photo</h2>
          <div className="mt-3 grid gap-4 md:grid-cols-[minmax(0,1fr)_200px]">
            <div className="space-y-3">
              <label className="block text-sm font-medium text-navy">Photo link
                <input inputMode="url" placeholder="https://…/front-desk.jpg" value={url} onChange={(e) => { setUrl(e.target.value); setPreviewOk(null); }} aria-describedby="photo-help"
                  className="mt-1 min-h-11 w-full rounded-lg border border-ink-300 bg-white px-3 text-sm sm:min-h-10" />
              </label>
              <p id="photo-help" className={clsx("text-[13px]", url && !valid ? "text-red-700" : "text-ink-500")}>{url && !valid ? "The link must start with https://" : "Paste a public link to a photo you own. Google fetches it."}</p>
              <fieldset><legend className="mb-1.5 text-sm font-medium text-navy">What is it a photo of?</legend>
                <div className="flex flex-wrap gap-1.5">{KINDS.map(([k, l]) => (
                  <button key={k} type="button" aria-pressed={cat === k} onClick={() => setCat(k)} className={clsx("min-h-11 rounded-full px-3.5 text-sm font-medium transition-colors sm:min-h-9", cat === k ? "bg-navy text-white" : "bg-ink-100/70 text-navy hover:bg-brand-100")}>{l}</button>))}</div></fieldset>
              <Button loading={busy} disabled={!valid || previewOk === false} icon={<ImagePlus className="h-4 w-4" />} onClick={() => void add()}>Add to Google</Button>
              {previewOk === false && <p className="text-[13px] text-red-700">That link doesn&rsquo;t open as a picture, so Google can&rsquo;t fetch it either. Check the link.</p>}
            </div>
            <div aria-live="polite" className="grid aspect-[4/3] place-items-center overflow-hidden rounded-xl bg-brand-50 text-center">
              {valid ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={url} alt="Preview of the photo you are adding" referrerPolicy="no-referrer" onLoad={() => setPreviewOk(true)} onError={() => setPreviewOk(false)} className={clsx("h-full w-full object-cover", previewOk === false && "hidden")} />
              ) : <div className="px-4"><Camera className="mx-auto h-7 w-7 text-brand-700" strokeWidth={1.5} aria-hidden /><p className="mt-1 text-sm font-medium text-navy">Preview</p><p className="text-xs text-ink-500">Your photo shows here before you add it</p></div>}
              {valid && previewOk === false && <p className="px-4 text-sm text-ink-500">No preview</p>}
            </div>
          </div>
        </section>
      )}

      <section aria-label="Your photos">
        <div role="group" aria-label="Filter by photo type" className="mb-3 flex flex-wrap gap-1.5">
          {[["ALL", "All"], ...KINDS.filter(([k]) => counts[k])].map(([k, l]) => (
            <button key={k} type="button" aria-pressed={filter === k} onClick={() => setFilter(k)} className={clsx("min-h-11 rounded-full px-3.5 text-sm font-medium transition-colors sm:min-h-9", filter === k ? "bg-navy text-white" : "bg-white text-navy ring-1 ring-ink-200 hover:bg-brand-50")}>
              {l}<span className="ml-1.5 text-xs opacity-70">{k === "ALL" ? data?.length ?? 0 : counts[k]}</span></button>))}
        </div>
        {loading && !data ? <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="aspect-square" />)}</div>
          : data && data.length === 0 ? (
            <div className="rounded-2xl bg-brand-50 p-8 text-center"><Camera className="mx-auto h-9 w-9 text-brand-700" strokeWidth={1.5} aria-hidden /><h3 className="mt-3 text-base font-bold text-navy">No photos on your profile yet</h3><p className="mx-auto mt-1 max-w-sm text-sm text-ink-700">Profiles with photos get more calls and direction requests. Start with a front-of-shop photo and your logo.</p></div>
          ) : (
            <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
              {shown.map((m) => (
                <li key={m.name}>
                  <button type="button" onClick={() => setOpen(m)} aria-label={`Open ${label(m.category)} photo`} className="group relative block w-full overflow-hidden rounded-xl bg-ink-100 text-left ring-1 ring-ink-100 transition-shadow hover:ring-2 hover:ring-brand-600">
                    <SafeImage m={m} className="aspect-square w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]" />
                    <span className="absolute bottom-2 left-2 rounded-full bg-white/95 px-2.5 py-1 text-xs font-semibold text-navy">{label(m.category)}</span>
                  </button>
                </li>))}
            </ul>)}
        <p className="mt-3 text-[13px] text-ink-500">Google checks each photo after it is added, so a new one can take a little while to appear.</p>
      </section>

      <Modal open={!!open} onClose={() => setOpen(null)} title={open ? `${label(open.category)} photo` : "Photo"}
        footer={open && <div className="flex flex-wrap justify-between gap-2">{open.url ? <a href={open.url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-brand-700 underline sm:min-h-9"><ExternalLink className="h-4 w-4" aria-hidden />Open on Google</a> : <span />}
          {isAdmin && <Button variant="danger" icon={<Trash2 className="h-4 w-4" />} onClick={() => void remove(open)}>Delete photo</Button>}</div>}>
        {open && <><SafeImage m={open} className="max-h-[60vh] w-full rounded-lg object-contain" /><p className="mt-2 text-[13px] text-ink-500">{open.created_at ? `Added ${fmtDate(open.created_at)}` : "On your Google profile"}</p></>}
      </Modal>
    </div>
  );
}
