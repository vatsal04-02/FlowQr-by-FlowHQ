"use client";
import { Download, ImagePlus, RotateCcw, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { QrPreview, QrStyleEditor, styleProblem } from "@/components/QrStyleEditor";
import { Button } from "@/components/ui/Button";
import { Alert, PageHeader, Skeleton } from "@/components/ui/Card";
import { Panel, Status } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, apiFile, errorMessage, saveBlob } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { CARD_STATUS } from "@/lib/card-ui";
import type { Campaign } from "@/lib/review-growth";
import { DEFAULT_QR_STYLE, type Card, type QRStyle, type QRStyleInfo } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

const MAX_LOGO = 512 * 1024;
const MAX_BULK = 200;
type Fmt = "png" | "svg" | "pdf";

/** What each failure means for the person looking at the screen. */
function explain(e: unknown): string {
  if (!(e instanceof ApiError)) return "Something went wrong. Please try again.";
  if (e.code === "qr_not_scannable") return e.message;
  if (e.status === 413) return "That logo is larger than 512 KB. Use a smaller file.";
  if (e.status === 429) return "Too many requests just now. Wait a few minutes and try again.";
  if (e.status === 403) return "Only owners and admins can change QR designs or export codes.";
  if (e.status === 404) return "One of the selected codes no longer exists or isn't yours. Refresh the page and select again.";
  return e.message;
}

export default function QrPage() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const info = useFetch<QRStyleInfo>("/qr/style");
  const [style, setStyle] = useState<QRStyle | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [logoBusy, setLogoBusy] = useState(false);
  const [logoVersion, setLogoVersion] = useState(0);
  const file = useRef<HTMLInputElement>(null);

  useEffect(() => { if (info.data && style === null) setStyle(info.data.style); }, [info.data, style]);
  const dirty = !!(style && info.data && JSON.stringify(style) !== JSON.stringify(info.data.style));
  const problem = style ? styleProblem(style) : null;

  async function save() {
    if (!style) return;
    setSaving(true); setSaveError(null);
    try { const d = await api<QRStyleInfo>("/qr/style", { method: "PUT", body: style }); info.setData(d); setStyle(d.style); toast("Design saved. New downloads use it; printed codes are not affected."); }
    catch (e) { setSaveError(explain(e)); } finally { setSaving(false); }
  }
  async function reset() {
    if (!confirm("Go back to the plain FlowQR design? Your logo is removed too. Printed codes are not affected.")) return;
    setSaving(true); setSaveError(null);
    try { const d = await api<QRStyleInfo>("/qr/style", { method: "DELETE" }); info.setData(d); setStyle(d.style); setLogoVersion((v) => v + 1); toast("Back to the plain design."); }
    catch (e) { setSaveError(explain(e)); } finally { setSaving(false); }
  }
  async function uploadLogo(f: File) {
    setSaveError(null);
    if (!["image/png", "image/jpeg", "image/webp"].includes(f.type)) { setSaveError("The logo must be a PNG, JPEG or WebP image."); return; }
    if (f.size > MAX_LOGO) { setSaveError("That logo is larger than 512 KB. Use a smaller file."); return; }
    setLogoBusy(true);
    try { const d = await api<QRStyleInfo>("/qr/style/logo", { method: "PUT", raw: f }); info.setData(d); setLogoVersion((v) => v + 1); toast("Logo uploaded. Turn it on below to use it."); }
    catch (e) { setSaveError(explain(e)); } finally { setLogoBusy(false); if (file.current) file.current.value = ""; }
  }
  async function removeLogo() {
    setLogoBusy(true); setSaveError(null);
    try { const d = await api<QRStyleInfo>("/qr/style/logo", { method: "DELETE" }); info.setData(d); setStyle((s) => (s ? { ...s, use_logo: false } : s)); setLogoVersion((v) => v + 1); toast("Logo removed."); }
    catch (e) { setSaveError(explain(e)); } finally { setLogoBusy(false); }
  }

  return (
    <>
      <PageHeader eyebrow="Cards" title="QR design & export" subtitle="Change how your QR codes look and download them for printing. The design never changes where a code leads, so codes you have already printed keep working." />
      {info.error && <Alert tone="error" title="Couldn't load your QR design">{info.error}</Alert>}
      {!isAdmin && <div className="mb-4"><Alert tone="info" title="View only">Owners and admins can change the design and export codes.</Alert></div>}
      <div className="grid gap-4 lg:grid-cols-[1fr_300px]">
        <Panel title="Design" meta={info.data ? (info.data.is_default ? "plain FlowQR design" : "custom design") : undefined}>
          {!style || !info.data ? <Skeleton className="h-72" /> : (
            <div className="space-y-4">
              {saveError && <Alert tone="error" title="Not saved">{saveError}</Alert>}
              <div className="flex flex-wrap items-center gap-3 rounded-lg border border-ink-100 p-3">
                <div className="grid h-14 w-14 shrink-0 place-items-center overflow-hidden rounded-lg border border-ink-100 bg-white">
                  {info.data.has_logo
                    // eslint-disable-next-line @next/next/no-img-element
                    ? <img key={logoVersion} src={`/api/v1/qr/style/logo.png?v=${logoVersion}`} alt="Your uploaded logo" className="h-full w-full object-contain" />
                    : <ImagePlus className="h-5 w-5 text-ink-400" aria-hidden />}
                </div>
                <div className="min-w-0 flex-1"><p className="text-sm font-medium">Logo</p><p className="text-xs text-ink-500">{info.data.has_logo ? "Uploaded. PNG, JPEG or WebP, up to 512 KB." : "None yet. PNG, JPEG or WebP, up to 512 KB."}</p></div>
                {isAdmin && <>
                  <input ref={file} type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" aria-label="Choose a logo file" onChange={(e) => { const f = e.target.files?.[0]; if (f) void uploadLogo(f); }} />
                  <Button size="sm" variant="secondary" loading={logoBusy} icon={<ImagePlus className="h-4 w-4" />} onClick={() => file.current?.click()}>{info.data.has_logo ? "Replace" : "Upload"}</Button>
                  {info.data.has_logo && <Button size="sm" variant="ghost" disabled={logoBusy} icon={<Trash2 className="h-4 w-4 text-red-600" />} onClick={() => void removeLogo()}>Remove</Button>}
                </>}
              </div>
              <QrStyleEditor value={style} onChange={(v) => { setStyle(v); setSaveError(null); }} hasLogo={info.data.has_logo} disabled={!isAdmin} />
              {isAdmin && (
                <div className="flex flex-wrap items-center gap-2 border-t border-ink-100 pt-4">
                  <Button loading={saving} disabled={!dirty || !!problem} onClick={() => void save()}>Save design</Button>
                  {dirty && <Button variant="secondary" disabled={saving} onClick={() => { setStyle(info.data!.style); setSaveError(null); }}>Discard changes</Button>}
                  {!info.data.is_default && <Button variant="ghost" disabled={saving} icon={<RotateCcw className="h-4 w-4" />} onClick={() => void reset()}>Reset to plain</Button>}
                </div>)}
              <p className="text-xs text-ink-500">{info.data.verification === "decoded"
                ? "Before a design is saved, FlowQR draws a code with it and reads it back with a scanner. Designs that don't read back are refused."
                : "The scanner check isn't available on this server right now, so only the colour and margin rules are applied."} Always test a printed copy with a phone before a large print run.</p>
            </div>)}
        </Panel>
        <aside aria-label="Preview">
          <Panel title="Preview">{style ? <QrPreview value={style} version={logoVersion} /> : <Skeleton className="h-64" />}</Panel>
        </aside>
      </div>
      {isAdmin && <BulkExport fallbackStyle={info.data?.style ?? DEFAULT_QR_STYLE} />}
    </>
  );
}

function BulkExport({ fallbackStyle }: { fallbackStyle: QRStyle }) {
  const toast = useToast();
  const cards = useFetch<Card[]>("/cards");
  const campaigns = useFetch<Campaign[]>("/review-growth/campaigns");
  const [pickedCards, setPickedCards] = useState<Set<string>>(new Set());
  const [pickedCampaigns, setPickedCampaigns] = useState<Set<string>>(new Set());
  const [formats, setFormats] = useState<Set<Fmt>>(new Set<Fmt>(["png", "svg", "pdf"]));
  const [sheet, setSheet] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const cardRows = cards.data ?? [];
  const campaignRows = useMemo(() => (campaigns.data ?? []).filter((c) => c.status !== "archived"), [campaigns.data]);
  const count = pickedCards.size + pickedCampaigns.size;
  const toggle = (set: Set<string>, apply: (s: Set<string>) => void, id: string) => { const n = new Set(set); if (n.has(id)) n.delete(id); else n.add(id); apply(n); };
  const all = (ids: string[], set: Set<string>, apply: (s: Set<string>) => void) => apply(set.size === ids.length ? new Set() : new Set(ids));

  async function run() {
    setError(null); setNote(null);
    if (!count) { setError("Select at least one card or campaign."); return; }
    if (count > MAX_BULK) { setError(`One export can hold up to ${MAX_BULK} codes. You selected ${count}; export in smaller groups.`); return; }
    if (!formats.size) { setError("Choose at least one file format."); return; }
    setBusy(true);
    try {
      const { blob, headers } = await apiFile("/qr/bulk", { method: "POST", body: { card_ids: [...pickedCards], campaign_ids: [...pickedCampaigns], formats: [...formats], sheet, size_px: fallbackStyle.size_px } });
      saveBlob(blob, "flowqr-codes.zip");
      const fallbacks = Number(headers.get("X-FlowQR-Style-Fallbacks") ?? 0);
      if (fallbacks > 0) setNote(`${fallbacks} code(s) were exported in the plain design because their custom design did not pass the scan check. They are marked "fallback-plain" in manifest.csv.`);
      toast(`Exported ${headers.get("X-FlowQR-Codes") ?? count} code(s).`);
    } catch (e) { setError(explain(e)); } finally { setBusy(false); }
  }

  return (
    <div className="mt-4">
      <Panel title="Bulk export" meta="ZIP with one file per code, a manifest and a print sheet">
        <p className="mb-3 text-sm text-ink-500">Exporting only draws the codes you already have. It doesn&rsquo;t create, replace or re-point anything.</p>
        {(cards.error || campaigns.error) && <div className="mb-3"><Alert tone="error">{cards.error ?? campaigns.error}</Alert></div>}
        {error && <div className="mb-3"><Alert tone="error" title="Nothing was exported">{error}</Alert></div>}
        {note && <div className="mb-3"><Alert tone="warning" title="Some designs were not applied">{note}</Alert></div>}
        <div className="grid gap-4 md:grid-cols-2">
          <PickList title="Cards" loading={cards.loading && !cards.data} empty="No cards assigned to this business yet."
            rows={cardRows.map((c) => ({ id: c.id, main: c.card_code, sub: `${c.label ?? "No label"} · ${c.location_name ?? "No location"}`, badge: <Status tone={CARD_STATUS[c.status].tone}>{CARD_STATUS[c.status].label}</Status> }))}
            picked={pickedCards} onToggle={(id) => toggle(pickedCards, setPickedCards, id)} onAll={() => all(cardRows.map((c) => c.id), pickedCards, setPickedCards)} />
          <PickList title="QR campaigns" loading={campaigns.loading && !campaigns.data} empty="No campaigns yet."
            rows={campaignRows.map((c) => ({ id: c.id, main: c.name, sub: c.location_name ?? "Location removed", badge: <Status tone={c.status === "active" ? "ok" : "warn"}>{c.status}</Status> }))}
            picked={pickedCampaigns} onToggle={(id) => toggle(pickedCampaigns, setPickedCampaigns, id)} onAll={() => all(campaignRows.map((c) => c.id), pickedCampaigns, setPickedCampaigns)} />
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-ink-100 pt-4 text-sm">
          <fieldset className="flex flex-wrap items-center gap-x-4 gap-y-2"><legend className="sr-only">File formats</legend>
            {(["png", "svg", "pdf"] as Fmt[]).map((f) => (
              <label key={f} className="flex min-h-11 items-center gap-1.5 sm:min-h-0"><input type="checkbox" className="h-[18px] w-[18px]" checked={formats.has(f)} onChange={() => { const n = new Set(formats); if (n.has(f)) n.delete(f); else n.add(f); setFormats(n); }} />{f.toUpperCase()}</label>))}
          </fieldset>
          <label className="flex min-h-11 items-center gap-1.5 sm:min-h-0"><input type="checkbox" className="h-[18px] w-[18px]" checked={sheet} onChange={(e) => setSheet(e.target.checked)} />A4 print sheet (12 per page)</label>
          <Button className="ml-auto" loading={busy} icon={<Download className="h-4 w-4" />} onClick={() => void run()}>Export {count ? `${count} code${count === 1 ? "" : "s"}` : "codes"}</Button>
        </div>
        <p className="mt-3 text-xs text-ink-500">Paused or deactivated codes can be exported too, but they show an inactive page when scanned until you turn them back on.</p>
      </Panel>
    </div>
  );
}

function PickList({ title, rows, picked, onToggle, onAll, loading, empty }: {
  title: string; rows: { id: string; main: string; sub: string; badge: React.ReactNode }[]; picked: Set<string>; onToggle: (id: string) => void; onAll: () => void; loading: boolean; empty: string;
}) {
  return (
    <div className="min-w-0 rounded-lg border border-ink-100">
      <div className="flex items-center justify-between gap-2 border-b border-ink-100 px-3 py-2">
        <p className="text-sm font-semibold">{title} <span className="font-normal text-ink-500">{picked.size ? `· ${picked.size} selected` : ""}</span></p>
        {rows.length > 0 && <button type="button" className="min-h-11 rounded-md px-2 text-[13px] font-medium text-brand-700 hover:bg-brand-50 sm:min-h-7" onClick={onAll}>{picked.size === rows.length ? "Clear" : "Select all"}</button>}
      </div>
      {loading ? <Skeleton className="m-3 h-24" /> : rows.length === 0 ? <p className="p-3 text-sm text-ink-500">{empty}</p> : (
        <ul className="max-h-64 divide-y divide-ink-100 overflow-y-auto">
          {rows.map((r) => (
            <li key={r.id}><label className="flex min-h-11 cursor-pointer items-center gap-3 px-3 py-1.5 hover:bg-ink-50">
              <input type="checkbox" className="h-[18px] w-[18px] shrink-0" checked={picked.has(r.id)} onChange={() => onToggle(r.id)} />
              <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{r.main}</span><span className="block truncate text-xs text-ink-500">{r.sub}</span></span>
              {r.badge}
            </label></li>))}
        </ul>)}
    </div>
  );
}
