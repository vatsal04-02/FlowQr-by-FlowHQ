"use client";
import { ArrowLeft, ExternalLink, Save, Upload } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { DetailsPanel, ImagesPanel, SectionsPanel, SeoPanel } from "@/components/admin/site/SitePanels";
import { EnquiriesPanel, HistoryPanel, PreviewPane, SettingsPanel } from "@/components/admin/site/SiteAdminPanels";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, PageHeader, Skeleton } from "@/components/ui/Card";
import { Segmented } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import { COMMERCIAL_LABEL, COMMERCIAL_TONE, errorMap, nextStep, STATUS_LABEL, STATUS_TONE, type Catalogue, type SiteConfig, type SiteContent, type SiteInfo } from "@/lib/sites";

type Tab = "details" | "sections" | "images" | "seo" | "enquiries" | "history" | "settings";
const TABS: [Tab, string][] = [["details", "Details"], ["sections", "Sections"], ["images", "Images"], ["seo", "Search"], ["enquiries", "Enquiries"], ["history", "History"], ["settings", "Settings"]];

export function SiteEditor({ siteId, tenantId }: { siteId: string; tenantId: string }) {
  const toast = useToast();
  const site = useFetch<SiteInfo>(`/admin/sites/${siteId}`);
  const catQ = useFetch<Catalogue>("/admin/sites/templates");
  const cfgQ = useFetch<SiteConfig>("/admin/sites/config");
  const [tab, setTab] = useState<Tab>("sections");
  const [draft, setDraft] = useState<SiteContent | null>(null);
  const [base, setBase] = useState<string>("");     // JSON of the content as last synced with the server
  const [synced, setSynced] = useState<number>(0);   // the draft_version that content came from
  const [errors, setErrors] = useState<{ path: string; message: string }[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const dirty = draft !== null && JSON.stringify(draft) !== base;
  const s = site.data;
  useEffect(() => {
    if (s?.draft_content && !dirty && s.draft_version !== synced) { setDraft(s.draft_content); setBase(JSON.stringify(s.draft_content)); setSynced(s.draft_version); setErrors([]); }
  }, [s, dirty, synced]);
  // leaving with unsaved work asks first
  useEffect(() => {
    if (!dirty) return;
    const h = (e: BeforeUnloadEvent) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", h);
    return () => window.removeEventListener("beforeunload", h);
  }, [dirty]);

  const errs = useMemo(() => errorMap(errors), [errors]);
  const ctx = useMemo(() => ({ siteId, assets: s?.assets ?? [], errors: errs }), [siteId, s?.assets, errs]);

  async function save() {
    if (!draft) return;
    setBusy("save");
    try {
      const r = await api<SiteInfo>(`/admin/sites/${siteId}/content`, { method: "PUT", body: { content: draft, base_version: synced } });
      setErrors([]); setSynced(r.draft_version); setBase(JSON.stringify(r.draft_content)); setDraft(r.draft_content ?? draft);
      toast("Draft saved."); await site.reload();
    } catch (e) {
      if (e instanceof ApiError && e.code === "invalid_content") { setErrors((e.detail as { errors: { path: string; message: string }[] }).errors); toast("Some fields need attention.", "error"); }
      else if (e instanceof ApiError && e.code === "version_conflict") { toast("Someone else changed this website. Your changes were not saved; discard them to load the latest.", "error"); }
      else toast(errorMessage(e), "error");
    } finally { setBusy(null); }
  }
  function discard() { if (s?.draft_content) { setDraft(s.draft_content); setBase(JSON.stringify(s.draft_content)); setSynced(s.draft_version); setErrors([]); void site.reload(); } }
  async function publish() {
    if (!confirm(`Publish this website now? It becomes visible to everyone at ${s?.hostname}.`)) return;
    setBusy("publish");
    try { await api(`/admin/sites/${siteId}/publish`, { method: "POST", body: {} }); toast("Published."); await site.reload(); }
    catch (e) { toast(errorMessage(e), "error"); await site.reload(); } finally { setBusy(null); }
  }

  if (site.error) return <Alert tone="error">{site.error}</Alert>;
  if (!s || !catQ.data || !cfgQ.data || !draft) return <Skeleton className="h-96" />;
  const cat = catQ.data, cfg = cfgQ.data;
  const blockers = s.readiness ?? [];
  const live = s.status === "published";

  return (
    <>
      <Link href={`/admin/customers/${tenantId}`} className="mb-4 inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-brand-700 hover:underline"><ArrowLeft className="h-4 w-4" aria-hidden />Back to the business</Link>
      <PageHeader eyebrow="Website" title={draft.business.name as string}
        subtitle={`${cat.templates.find((t) => t.key === s.template_key)?.label} template · draft saved ${fmtDate(s.updated_at, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}`}
        actions={<>
          <Button variant="secondary" icon={<Save className="h-4 w-4" />} loading={busy === "save"} disabled={!dirty} onClick={() => void save()}>Save draft</Button>
          <Button icon={<Upload className="h-4 w-4" />} loading={busy === "publish"} disabled={dirty || blockers.length > 0 || s.status === "suspended"} onClick={() => void publish()}>{live ? "Publish update" : "Publish"}</Button>
        </>} />

      <Card className="mb-5" pad={false}>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 p-4" data-testid="status-strip">
          <Badge tone={STATUS_TONE[s.status]}>{STATUS_LABEL[s.status]}</Badge>
          <Badge tone={COMMERCIAL_TONE[s.commercial.status]}>{COMMERCIAL_LABEL[s.commercial.status] ?? s.commercial.status}</Badge>
          {live ? <a href={s.url} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1 text-sm font-semibold text-brand-700 hover:underline">{s.hostname}<ExternalLink className="h-3.5 w-3.5" aria-hidden /></a> : <span className="text-sm text-muted">{s.hostname} (not live)</span>}
          {s.live_version > 0 && <span className="text-sm text-muted">Version {s.live_version}{s.published_at ? ` · published ${fmtDate(s.published_at, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}` : ""}</span>}
          {s.enquiries.new > 0 && <button type="button" className="text-sm font-semibold text-brand-700 hover:underline" onClick={() => setTab("enquiries")}>{s.enquiries.new} new enquir{s.enquiries.new === 1 ? "y" : "ies"}</button>}
        </div>
        <p className="border-t border-line px-4 py-3 text-sm text-ink-700" role="status">{nextStep(s, blockers.length, dirty)}</p>
        {s.publish_error && <div className="border-t border-line p-4"><Alert tone="error" title="The last publish failed">{s.publish_error} The website that was live has not changed.</Alert></div>}
        {dirty && s.draft_version !== synced && <div className="border-t border-line p-4"><Alert tone="warning" title="Someone else changed this website">Your edits were made on an older version. <button type="button" className="font-semibold underline" onClick={discard}>Discard my changes and load the latest</button>.</Alert></div>}
      </Card>

      {errors.length > 0 && <div className="mb-5"><Alert tone="error" title={`${errors.length} field${errors.length === 1 ? "" : "s"} need attention`}>{errors.slice(0, 4).map((e) => e.message).join(" ")} The fields are marked in the editor.</Alert></div>}
      {blockers.length > 0 && !dirty && (
        <details className="mb-5 rounded-2xl border border-line bg-surface p-4" open={blockers.length <= 6}>
          <summary className="cursor-pointer font-semibold">Before this can be published ({blockers.length})</summary>
          <ul className="mt-3 list-disc space-y-1 pl-5 text-sm text-ink-700">{blockers.map((b, i) => <li key={i}>{b.message}</li>)}</ul>
        </details>
      )}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,34rem)]">
        <div className="min-w-0 space-y-5">
          <div className="overflow-x-auto"><Segmented<Tab> label="Editor section" value={tab} onChange={setTab} options={TABS} /></div>
          {tab === "details" && <DetailsPanel cat={cat} draft={draft} set={setDraft} ctx={ctx} />}
          {tab === "sections" && <SectionsPanel cat={cat} draft={draft} set={setDraft} ctx={ctx} template={s.template_key} />}
          {tab === "images" && <ImagesPanel site={s} reload={site.reload} readOnly={false} />}
          {tab === "seo" && <SeoPanel draft={draft} set={setDraft} ctx={ctx} host={s.hostname} />}
          {tab === "enquiries" && <EnquiriesPanel site={s} reload={site.reload} />}
          {tab === "history" && <HistoryPanel site={s} reload={site.reload} dirty={dirty} />}
          {tab === "settings" && <SettingsPanel site={s} cat={cat} cfg={cfg} reload={site.reload} dirty={dirty} />}
        </div>
        <div className="min-w-0 xl:sticky xl:top-4 xl:self-start"><PreviewPane siteId={siteId} version={s.draft_version} dirty={dirty} /></div>
      </div>
    </>
  );
}
