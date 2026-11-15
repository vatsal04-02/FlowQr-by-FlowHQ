"use client";
import { Download, Plus, QrCode } from "lucide-react";
import { PosterDownload } from "@/components/cards/PosterDownload";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { StatusBadge, useCampaigns } from "@/components/review-growth/shared";
import { Button } from "@/components/ui/Button";
import { Alert, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { ErrorSummary, Input, Select } from "@/components/ui/Form";
import { Segmented } from "@/components/ui/kit";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtNum, timeAgo } from "@/lib/format";
import { useForm } from "@/lib/form";
import type { Campaign } from "@/lib/review-growth";
import type { Location } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

type Filter = "all" | "active" | "paused" | "archived";

export default function CampaignsPage() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useCampaigns(true);
  const locs = useFetch<Location[]>("/locations");
  const [filter, setFilter] = useState<Filter>("active");
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const activeLocs = useMemo(() => (locs.data ?? []).filter((l) => l.is_active), [locs.data]);
  const f = useForm({ name: "", location_id: "" }, {
    name: (v) => (String(v).trim().length >= 2 ? undefined : "Give the campaign a name (at least 2 characters)"),
    location_id: (v) => (v ? undefined : "Choose a location"),
  });

  useEffect(() => { if (new URLSearchParams(window.location.search).get("new")) setOpen(true); }, []);

  const shown = (data ?? []).filter((c) => filter === "all" || c.status === filter);

  async function create(e: React.FormEvent) {
    e.preventDefault(); f.setServerError(null);
    if (!f.validateAll()) return;
    setBusy(true);
    try {
      const c = await api<Campaign>("/review-growth/campaigns", { method: "POST", body: { name: f.values.name.trim(), location_id: f.values.location_id } });
      toast("Campaign created. Download its QR code below.");
      setOpen(false); f.setValues({ name: "", location_id: "" });
      window.location.assign(`/gbp/campaigns/${c.id}`);
    } catch (err) { f.fail(errorMessage(err)); } finally { setBusy(false); }
  }

  return (
    <>
      <PageHeader eyebrow="Review Growth" title="QR campaigns" subtitle="Each campaign is a QR code that opens a branded review page for one location."
        actions={<>
          <Segmented label="Show" value={filter} onChange={setFilter} options={[["active", "Active"], ["paused", "Paused"], ["archived", "Archived"], ["all", "All"]] as const} />
          {isAdmin && <Button size="sm" icon={<Plus className="h-4 w-4" />} onClick={() => setOpen(true)}>New campaign</Button>}
        </>} />
      {error && <Alert tone="error">{error}</Alert>}
      {loading && !data ? <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-56" />)}</div>
        : data && data.length === 0 ? (
          <EmptyState icon={<QrCode className="h-5 w-5" />} title="No campaigns yet"
            action={isAdmin ? <Button size="sm" onClick={() => setOpen(true)}>Create a campaign</Button> : undefined}>
            Create one per place you want to collect reviews: front desk, tables, receipts. Each gets its own QR code and statistics.</EmptyState>
        ) : (
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {shown.map((c) => (
              <li key={c.id} className="panel flex flex-col overflow-hidden">
                <Link href={`/gbp/campaigns/${c.id}`} className="group flex items-center gap-4 p-4" aria-label={`Open ${c.name}`}>
                  <span className="grid h-24 w-24 shrink-0 place-items-center overflow-hidden rounded-lg border border-ink-100 bg-white">
                    {isAdmin && c.status !== "archived"
                      ? /* eslint-disable-next-line @next/next/no-img-element */ <img src={`/api/v1/review-growth/campaigns/${c.id}/qr.svg`} alt={`QR code for ${c.name}`} className="h-full w-full object-contain p-1" loading="lazy" />
                      : <QrCode className="h-8 w-8 text-ink-300" aria-hidden />}
                  </span>
                  <span className="min-w-0"><span className="block truncate font-semibold group-hover:text-brand-700">{c.name}</span>
                    <span className="block truncate text-[13px] text-ink-500">{c.location_name ?? "Location removed"}</span>
                    <span className="mt-1.5 block"><StatusBadge status={c.status} /></span></span>
                </Link>
                <dl className="mt-auto grid grid-cols-4 divide-x divide-ink-100 border-t border-ink-100 text-center">
                  {([["Scans", c.stats.scans], ["Feedback", c.stats.feedback_submitted], ["Approved", c.stats.drafts_approved], ["To Google", c.stats.google_redirects]] as const).map(([k, v]) => (
                    <div key={k} className="px-1 py-2"><dd className="num text-sm font-semibold">{fmtNum(v)}</dd><dt className="text-[11px] text-ink-500">{k}</dt></div>))}
                </dl>
                <div className="flex items-center justify-between gap-2 border-t border-ink-100 px-4 py-2 text-xs text-ink-500">
                  <span>Created {timeAgo(c.created_at)}{!c.review_url_ready && <span className="ml-2 font-medium text-amber-800">No Google link</span>}</span>
                  {isAdmin && c.status !== "archived" && <span className="flex items-center gap-1"><PosterDownload path={`/review-growth/campaigns/${c.id}/poster`} filename={`flowqr-${c.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "campaign"}`} label="Poster" variant="ghost" /><a className="inline-flex min-h-11 items-center gap-1 rounded-md px-2 text-[13px] font-medium text-brand-700 hover:bg-brand-50 sm:min-h-7" href={`/api/v1/review-growth/campaigns/${c.id}/qr.png`} download><Download className="h-3.5 w-3.5" aria-hidden />PNG</a></span>}
                </div>
              </li>
            ))}
          </ul>
        )}
      {data && data.length > 0 && shown.length === 0 && <p className="mt-4 text-sm text-ink-500">No {filter} campaigns.</p>}

      <Modal open={open} onClose={() => setOpen(false)} title="New QR campaign"
        footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button><Button type="submit" form="new-campaign" loading={busy}>Create campaign</Button></>}>
        <form id="new-campaign" onSubmit={create} noValidate className="space-y-4">
          <ErrorSummary errors={f.errors} serverError={f.serverError} summaryRef={f.summaryRef} />
          <Input label="Campaign name" placeholder="e.g. Front desk QR" maxLength={120} required {...f.bind("name")} />
          <Select label="Location" required hint={activeLocs.length === 0 ? "Add a location first under Locations." : "Customers will be sent to this location's Google review page."} {...f.bind("location_id")}>
            <option value="">Choose a location…</option>
            {activeLocs.map((l) => <option key={l.id} value={l.id}>{l.name}{l.city ? ` · ${l.city}` : ""}</option>)}
          </Select>
        </form>
      </Modal>
    </>
  );
}
