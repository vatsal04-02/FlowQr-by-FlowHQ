"use client";
import { Globe } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader } from "@/components/ui/Card";
import { Input, Select, Textarea } from "@/components/ui/Form";
import { Modal } from "@/components/ui/Modal";
import { api, errorMessage } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import { COMMERCIAL_LABEL, COMMERCIAL_TONE, STATUS_LABEL, STATUS_TONE, addressFor, type Catalogue, type SiteConfig, type SiteInfo } from "@/lib/sites";

interface Summary { enabled: boolean; website_interest?: "has_site" | "wants_site" | "not_now" | null; website_url?: string | null; suggested_template: string; suggested_slug: string | null; site: SiteInfo | null }

/** The Website section of a business page: whether it has a website, its state and address, and the way into the editor. Creating one needs an explicit hosting status: hosting is never free by default. */
export function WebsiteCard({ tenantId }: { tenantId: string }) {
  const router = useRouter();
  const q = useFetch<Summary>(`/admin/tenants/${tenantId}/site`);
  const cfg = useFetch<SiteConfig>("/admin/sites/config");
  const cat = useFetch<Catalogue>("/admin/sites/templates");
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ template: "", slug: "", status: "complimentary", reason: "", period: "monthly", until: "" });
  const [check, setCheck] = useState<{ available: boolean; problem: string | null } | null>(null);
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const s = q.data;
  const asked = useRef(false);
  // "Generate site" in the business list arrives here as ?website=create: open the form once, as soon as it can be used
  useEffect(() => {
    if (asked.current || !s?.enabled || s.site || typeof window === "undefined" || new URLSearchParams(window.location.search).get("website") !== "create") return;
    asked.current = true; start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [s]);

  function start() { setErr(null); setCheck(null); setF({ template: s?.suggested_template ?? "professional", slug: s?.suggested_slug ?? "", status: "complimentary", reason: "", period: "monthly", until: "" }); setOpen(true); }
  useEffect(() => {
    if (!open || f.slug.length < 3) { setCheck(null); return; }
    const t = setTimeout(() => { api<{ available: boolean; problem: string | null }>("/admin/sites/slug-check", { params: { slug: f.slug, tenant_id: tenantId } }).then(setCheck).catch(() => setCheck(null)); }, 350);
    return () => clearTimeout(t);
  }, [f.slug, open, tenantId]);

  async function create() {
    setBusy(true); setErr(null);
    try {
      const body = { template_key: f.template, site_slug: f.slug, commercial_status: f.status, commercial_reason: f.reason.trim() || null, billing_period: f.status === "paid_offline" ? f.period : null, paid_until: f.status === "paid_offline" ? f.until || null : null };
      await api(`/admin/tenants/${tenantId}/site`, { method: "POST", body });
      router.push(`/admin/customers/${tenantId}/website`);
    } catch (e) { setErr(errorMessage(e)); setBusy(false); }
  }
  const ready = f.slug.length >= 3 && check?.available !== false && (f.status === "complimentary" ? f.reason.trim().length >= 5 : !!f.until);

  return (
    <Card><CardHeader title="Website" action={s?.site ? <Link href={`/admin/customers/${tenantId}/website`} className="inline-flex min-h-9 items-center rounded-full bg-surface-2 px-4 text-sm font-semibold hover:bg-ink-100">Open editor</Link> : undefined} />
      {q.error && <Alert tone="error">{q.error}</Alert>}
      {s && !s.enabled && <p className="text-sm text-ink-500">Websites are switched off on this server. Nothing about this business changes while they are off.</p>}
      {s?.enabled && !s.site && (
        <>
          {s.website_interest === "wants_site" && <p className="mb-3 rounded-xl bg-amber-50 p-3 text-sm font-medium text-amber-900">This business said during onboarding that it would like FlowQR to build a website for it.</p>}
          {s.website_interest === "has_site" && <p className="mb-3 text-sm text-ink-500">It says it already has a website{s.website_url ? <>: <a href={s.website_url} target="_blank" rel="noopener noreferrer" className="font-semibold text-brand-700 hover:underline">{s.website_url}</a></> : ""}.</p>}
          <p className="mb-3 text-sm text-ink-700">This business has no website. Create one from a template, fill it from the business record, then publish it at its own address. The shopkeeper does not need a FlowQR login.</p>
          <Button icon={<Globe className="h-4 w-4" />} onClick={start}>Create website</Button>
        </>
      )}
      {s?.site && (
        <dl className="grid grid-cols-2 gap-3 text-sm">
          <div><dt className="text-ink-500">Status</dt><dd className="mt-0.5"><Badge tone={STATUS_TONE[s.site.status]}>{STATUS_LABEL[s.site.status]}</Badge></dd></div>
          <div><dt className="text-ink-500">Hosting</dt><dd className="mt-0.5"><Badge tone={COMMERCIAL_TONE[s.site.commercial.status]}>{COMMERCIAL_LABEL[s.site.commercial.status]}</Badge></dd></div>
          <div className="col-span-2"><dt className="text-ink-500">Address</dt><dd className="mt-0.5 break-all font-semibold">{s.site.status === "published" ? <a href={s.site.url} target="_blank" rel="noopener noreferrer" className="text-brand-700 hover:underline">{s.site.hostname}</a> : s.site.hostname}</dd></div>
          <div><dt className="text-ink-500">Enquiries</dt><dd className="mt-0.5 font-semibold">{s.site.enquiries.new} new · {s.site.enquiries.total} total</dd></div>
          <div><dt className="text-ink-500">{s.site.live_version ? "Published" : "Created"}</dt><dd className="mt-0.5 font-semibold">{fmtDate(s.site.published_at ?? s.site.created_at)}</dd></div>
        </dl>
      )}
      <Modal open={open} onClose={() => setOpen(false)} title="Create a website" footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button><Button loading={busy} disabled={!ready} onClick={() => void create()}>Create website</Button></>}>
        <div className="space-y-4">
          {err && <Alert tone="error">{err}</Alert>}
          <Select label="Template" value={f.template} onChange={(e) => setF({ ...f, template: e.target.value })} hint={cat.data?.templates.find((t) => t.key === f.template)?.description}>
            {(cat.data?.templates ?? []).map((t) => <option key={t.key} value={t.key}>{t.label}{t.key === s?.suggested_template ? " (suggested)" : ""}</option>)}
          </Select>
          <Input label="Site name" value={f.slug} onChange={(e) => setF({ ...f, slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "") })} error={check && !check.available ? check.problem ?? "Not available" : undefined}
                 hint={check?.available ? `Available: ${addressFor(cfg.data, f.slug)}` : `The website will be at ${addressFor(cfg.data, f.slug || "name")}`} />
          <fieldset className="space-y-3 rounded-2xl border border-line p-4">
            <legend className="px-1 text-sm font-semibold">Hosting</legend>
            <p className="text-sm text-muted">Hosting is never free by default. Record how this website is paid for (reference price: ₹{cfg.data?.pricing.monthly_inr ?? 199} a month, or ₹{cfg.data?.pricing.annual_inr ?? 1999} a year, no setup fee). Nothing is billed from here.</p>
            <Select label="This website is" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}><option value="complimentary">Complimentary (free, with a reason)</option><option value="paid_offline">Paid (recorded offline)</option></Select>
            {f.status === "complimentary"
              ? <Textarea label="Why is it free? (required, kept in the audit log)" rows={2} value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} />
              : <div className="grid gap-3 sm:grid-cols-2"><Select label="Billing" value={f.period} onChange={(e) => setF({ ...f, period: e.target.value })}><option value="monthly">Monthly</option><option value="annual">Annual</option></Select><Input label="Paid until" type="date" value={f.until} onChange={(e) => setF({ ...f, until: e.target.value })} /></div>}
          </fieldset>
        </div>
      </Modal>
    </Card>
  );
}
