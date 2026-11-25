"use client";
import { Download, RefreshCw, RotateCcw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, EmptyState } from "@/components/ui/Card";
import { Input, Select, Textarea } from "@/components/ui/Form";
import { Segmented } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, apiFile, errorMessage } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import { COMMERCIAL_LABEL, COMMERCIAL_TONE, DEVICES, SETTABLE_COMMERCIAL, addressFor, commercialChoice, daysUntil, fitScale, type Catalogue, type Device, type EnquiryInfo, type SiteConfig, type SiteInfo } from "@/lib/sites";

type Reload = () => Promise<unknown> | void;
const stamp = (v: string | null | undefined) => (v ? fmtDate(v, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "–");

/** Runs a call, toasts, reloads. */
function useAct(reload: Reload) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  async function act(name: string, fn: () => Promise<unknown>, ok: string): Promise<boolean> {
    setBusy(name); setErr(null);
    try { await fn(); toast(ok); await reload(); return true; } catch (e) { setErr(errorMessage(e)); return false; } finally { setBusy(null); }
  }
  return { busy, err, act, setErr };
}

// ---------------------------------------------------------------------------------------------------------------- preview
export function PreviewPane({ siteId, version, dirty }: { siteId: string; version: number; dirty: boolean }) {
  const [device, setDevice] = useState<Device>("desktop");
  const [html, setHtml] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const box = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(600);
  useEffect(() => {
    const el = box.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => setW(el.clientWidth));
    ro.observe(el); setW(el.clientWidth);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    let live = true;
    setErr(null);
    apiFile(`/admin/sites/${siteId}/preview`).then(async ({ blob }) => { const t = await blob.text(); if (live) setHtml(t); }).catch((e) => { if (live) setErr(errorMessage(e)); });
    return () => { live = false; };
  }, [siteId, version, tick]);
  const d = DEVICES[device], scale = fitScale(device, w);
  return (
    <Card><CardHeader title="Preview" action={<div className="flex items-center gap-2"><Segmented<Device> label="Device" value={device} onChange={setDevice} options={[["desktop", "Desktop"], ["mobile", "Mobile"]]} />
      <Button size="sm" variant="secondary" aria-label="Refresh preview" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={() => setTick((t) => t + 1)} /></div>} />
      {dirty && <p className="mb-2 text-xs text-muted" role="status">The preview shows your last saved draft. Save to see your latest changes.</p>}
      <div ref={box} className="overflow-hidden rounded-2xl border border-line bg-surface-2" style={{ height: d.height * scale }}>
        {err ? <p className="p-4 text-sm text-neg">{err}</p> : html === null ? <p className="p-4 text-sm text-muted">Loading the preview…</p> : (
          // The preview is the generated page, inlined with its images. sandbox="" gives it no scripts and no access to this page or its cookies.
          <iframe title={`${d.label} preview`} sandbox="" srcDoc={html} data-testid="preview-frame" style={{ width: d.width, height: d.height, transform: `scale(${scale})`, transformOrigin: "top left", border: 0, background: "#fff", marginLeft: device === "mobile" ? Math.max(0, (w - d.width * scale) / 2 / scale) : 0 }} />
        )}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------------------------------------------- settings: address, template, hosting status, commercial
export function SettingsPanel({ site, cat, cfg, reload, dirty }: { site: SiteInfo; cat: Catalogue; cfg: SiteConfig; reload: Reload; dirty: boolean }) {
  const { busy, err, act, setErr } = useAct(reload);
  const [slug, setSlug] = useState(site.site_slug), [tpl, setTpl] = useState(site.template_key);
  const [status, setStatus] = useState(commercialChoice(site.commercial.status)), [reason, setReason] = useState(""), [period, setPeriod] = useState(site.commercial.billing_period ?? "monthly"), [until, setUntil] = useState(site.commercial.paid_until ?? "");
  const [suspendWhy, setSuspendWhy] = useState("");
  const live = site.status === "published", c = site.commercial;
  const grace = daysUntil(c.grace_until);
  return (
    <div className="space-y-5">
      {err && <Alert tone="error">{err}</Alert>}
      <Card><CardHeader title="Address" />
        <p className="mb-3 text-sm text-muted">This website is served at <b>{addressFor(cfg, site.site_slug)}</b>. Custom domains are planned for a later phase.</p>
        <div className="flex flex-wrap items-end gap-3">
          <Input label="Site name" wrapperClassName="min-w-[14rem] flex-1" value={slug} onChange={(e) => setSlug(e.target.value.toLowerCase())} disabled={live} hint={live ? "Unpublish the website before changing its address." : "3 to 40 letters, numbers and hyphens. The old name is held for 90 days."} />
          <Button variant="secondary" loading={busy === "slug"} disabled={live || slug === site.site_slug} onClick={() => void act("slug", () => api(`/admin/sites/${site.id}/slug`, { method: "POST", body: { site_slug: slug } }), "Address changed.")}>Change address</Button>
        </div>
        <ul className="mt-4 divide-y divide-line text-sm">{site.domains.map((d) => <li key={d.id} className="flex items-center justify-between py-2"><span>{d.hostname}</span><span className="flex gap-2"><Badge tone="gray">{d.domain_type}</Badge><Badge tone={d.status === "active" ? "green" : "gray"}>{d.status}</Badge>{d.is_primary && <Badge tone="blue">primary</Badge>}</span></li>)}</ul>
        <p className="mt-3 text-xs text-muted">Custom domain: not available yet.</p>
      </Card>

      <Card><CardHeader title="Template" />
        <p className="mb-3 text-sm text-muted">Changing the template keeps the business details and any section the new template also has. {live && "Unpublish the website first."}</p>
        <div className="flex flex-wrap items-end gap-3">
          <Select label="Template" wrapperClassName="min-w-[14rem] flex-1" value={tpl} onChange={(e) => setTpl(e.target.value)} disabled={live}>{cat.templates.map((t) => <option key={t.key} value={t.key}>{t.label}</option>)}</Select>
          <Button variant="secondary" loading={busy === "tpl"} disabled={live || tpl === site.template_key || dirty} onClick={() => { if (confirm("Switch template? Sections the new template does not have are removed from the draft.")) void act("tpl", () => api(`/admin/sites/${site.id}/template`, { method: "POST", body: { template_key: tpl } }), "Template changed."); }}>Change template</Button>
        </div>
        {dirty && <p className="mt-2 text-xs text-muted">Save your changes first.</p>}
        <p className="mt-2 text-sm text-muted">{cat.templates.find((t) => t.key === tpl)?.description}</p>
      </Card>

      <Card><CardHeader title="Hosting status" action={<Badge tone={COMMERCIAL_TONE[c.status]}>{COMMERCIAL_LABEL[c.status] ?? c.status}</Badge>} />
        <dl className="mb-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
          {[["Billing", c.billing_period ?? "–"], ["Paid until", c.paid_until ? fmtDate(c.paid_until) : "–"], ["Grace ends", c.grace_until ? `${fmtDate(c.grace_until)}${grace !== null ? ` (${grace} days)` : ""}` : "–"], ["Edits this month", `${site.edits_this_month ?? 0} of ${cfg.pricing.edits_included_per_month} included`]]
            .map(([k, v]) => <div key={k}><dt className="text-muted">{k}</dt><dd className="mt-0.5 font-semibold">{v}</dd></div>)}
        </dl>
        {c.reason && <p className="mb-3 text-sm text-muted">Reason on record: {c.reason}</p>}
        {c.status === "expired" && <div className="mb-4"><Alert tone="warning">Hosting has expired. The website stays up until the grace period ends, then it is suspended. Nothing is deleted.</Alert></div>}
        <Alert tone="info" title="Recorded by hand">Nothing is billed from here. Reference price: ₹{cfg.pricing.monthly_inr} a month or ₹{cfg.pricing.annual_inr} a year, no setup fee, {cfg.pricing.edits_included_per_month} small edits a month included. Website hosting is separate from Launch, Growth and Scale.</Alert>
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <Select label="Set status to" value={status} onChange={(e) => setStatus(e.target.value)}>{SETTABLE_COMMERCIAL.map((k) => <option key={k} value={k}>{COMMERCIAL_LABEL[k]}</option>)}</Select>
          {status === "paid_offline" ? (
            <><Select label="Billing" value={period} onChange={(e) => setPeriod(e.target.value)}><option value="monthly">Monthly</option><option value="annual">Annual</option></Select>
              <Input label="Paid until" type="date" value={until} onChange={(e) => setUntil(e.target.value)} /></>
          ) : null}
          <Textarea label={status === "paid_offline" ? "Note (optional)" : "Reason (required, kept in the audit log)"} rows={2} className="sm:col-span-2" wrapperClassName="sm:col-span-2" value={reason} onChange={(e) => setReason(e.target.value)} />
        </div>
        <Button className="mt-3" loading={busy === "com"} disabled={status === c.status && !reason && status !== "paid_offline"} onClick={() => void act("com", () => api(`/admin/sites/${site.id}/commercial`, { method: "POST", body: { status, reason: reason || null, billing_period: status === "paid_offline" ? period : null, paid_until: status === "paid_offline" ? until || null : null } }), "Hosting status recorded.").then((ok) => ok && setReason(""))}>Record status</Button>
      </Card>

      <Card><CardHeader title="Take offline" />
        <div className="flex flex-wrap gap-3">
          {live && <Button variant="secondary" loading={busy === "unpub"} onClick={() => { if (confirm("Take the website offline? Visitors will see a not found page.")) void act("unpub", () => api(`/admin/sites/${site.id}/unpublish`, { method: "POST" }), "Website taken offline."); }}>Unpublish</Button>}
          {site.status === "suspended"
            ? <Button loading={busy === "resume"} onClick={() => void act("resume", () => api(`/admin/sites/${site.id}/unsuspend`, { method: "POST" }), "Website resumed.")}>Resume website</Button>
            : <div className="flex w-full flex-wrap items-end gap-3"><Input label="Suspend, with a reason" wrapperClassName="min-w-[14rem] flex-1" value={suspendWhy} onChange={(e) => setSuspendWhy(e.target.value)} hint="Visitors see a temporarily unavailable page. Nothing is deleted." />
              <Button variant="danger" loading={busy === "susp"} disabled={suspendWhy.trim().length < 5} onClick={() => void act("susp", () => api(`/admin/sites/${site.id}/suspend`, { method: "POST", body: { reason: suspendWhy.trim() } }), "Website suspended.").then((ok) => ok && setSuspendWhy(""))}>Suspend</Button></div>}
        </div>
        {!live && site.status !== "suspended" && <p className="mt-3 text-sm text-muted">This website is not live.</p>}
        <p className="mt-3 text-xs text-muted" onClick={() => setErr(null)}>Content is never deleted when hosting lapses or a site is suspended. It can be exported from the business's data export.</p>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------- enquiries
export function EnquiriesPanel({ site, reload }: { site: SiteInfo; reload: Reload }) {
  const toast = useToast();
  const [status, setStatus] = useState("");
  const list = useFetch<{ total: number; items: EnquiryInfo[] }>(`/admin/sites/${site.id}/enquiries`, { status, limit: 100 });
  const mark = async (id: string, s: string) => { try { await api(`/admin/sites/${site.id}/enquiries/${id}`, { method: "PATCH", body: { status: s } }); await list.reload(); await reload(); } catch (e) { toast(errorMessage(e), "error"); } };
  async function exportCsv() {
    try {
      const { blob } = await apiFile(`/admin/sites/${site.id}/enquiries.csv`);
      const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = `enquiries-${site.site_slug}.csv`; a.click(); URL.revokeObjectURL(url);
    } catch (e) { toast(errorMessage(e), "error"); }
  }
  return (
    <Card><CardHeader title={`Enquiries (${site.enquiries.total})`} action={<Button size="sm" variant="secondary" icon={<Download className="h-3.5 w-3.5" />} onClick={() => void exportCsv()}>Export CSV</Button>} />
      <div className="mb-3 max-w-[12rem]"><Select label="Show" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">All</option><option value="new">New</option><option value="contacted">Contacted</option><option value="resolved">Resolved</option><option value="spam">Spam</option></Select></div>
      {!list.data || list.data.items.length === 0 ? <EmptyState title="No enquiries">Messages sent from the website's form appear here. They are kept for a limited time and are never shown publicly.</EmptyState> : (
        <ul className="divide-y divide-line">{list.data.items.map((e) => (
          <li key={e.id} className="py-4" data-testid="enquiry-row">
            <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-semibold">{e.name} <Badge tone={e.status === "new" ? "amber" : e.status === "resolved" ? "green" : "gray"}>{e.status}</Badge></p><p className="text-xs text-muted">{stamp(e.received_at)}</p></div>
            <p className="mt-1 text-sm text-muted">{[e.phone, e.email].filter(Boolean).join(" · ")}</p>
            <p className="mt-2 whitespace-pre-wrap text-sm">{e.message}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {e.status !== "contacted" && <Button size="sm" variant="secondary" onClick={() => void mark(e.id, "contacted")}>Mark contacted</Button>}
              {e.status !== "resolved" && <Button size="sm" variant="secondary" onClick={() => void mark(e.id, "resolved")}>Mark resolved</Button>}
              {e.status !== "spam" && <Button size="sm" variant="secondary" onClick={() => void mark(e.id, "spam")}>Spam</Button>}
            </div>
          </li>))}</ul>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------------------------------------------- history
export function HistoryPanel({ site, reload, dirty }: { site: SiteInfo; reload: Reload; dirty: boolean }) {
  const { busy, err, act } = useAct(reload);
  return (
    <Card><CardHeader title="Published versions" />
      {err && <div className="mb-3"><Alert tone="error">{err}</Alert></div>}
      {site.revisions.length === 0 ? <EmptyState title="Nothing published yet">Each time the website is published, that version is kept here so you can go back to it.</EmptyState> : (
        <ul className="divide-y divide-line">{site.revisions.map((r, i) => (
          <li key={r.revision} className="flex flex-wrap items-center justify-between gap-2 py-3">
            <div><p className="font-semibold">Version {r.revision} {i === 0 && site.status === "published" && <Badge tone="green">live</Badge>}</p><p className="text-sm text-muted">{stamp(r.created_at)}{r.note ? ` · ${r.note}` : ""}</p></div>
            {i > 0 && <Button size="sm" variant="secondary" icon={<RotateCcw className="h-3.5 w-3.5" />} loading={busy === `rb${r.revision}`} disabled={dirty}
                                onClick={() => { if (confirm(`Publish version ${r.revision} again? It becomes a new version and replaces your current draft.`)) void act(`rb${r.revision}`, () => api(`/admin/sites/${site.id}/rollback`, { method: "POST", body: { revision: r.revision } }), `Version ${r.revision} is live again.`); }}>Go back to this</Button>}
          </li>))}</ul>
      )}
      {dirty && <p className="mt-3 text-xs text-muted">Save or discard your changes before going back to an earlier version.</p>}
    </Card>
  );
}
