"use client";
import { API_V1 } from "@/lib/config";
import { PosterDownload } from "@/components/cards/PosterDownload";
import { ArrowLeft, Download, ExternalLink, MapPin, Paintbrush, Palette, Pause, Play, RotateCcw, Sparkles, Trash2, TriangleAlert } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { QrPreview, QrStyleEditor, styleProblem } from "@/components/QrStyleEditor";
import { CopyButton, ReviewLinkEditor, StatusBadge } from "@/components/review-growth/shared";
import { LandingFrame, PreviewForm } from "@/components/review-growth/LandingFrame";
import { Button } from "@/components/ui/Button";
import { Alert, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input, Select } from "@/components/ui/Form";
import { KV, Panel } from "@/components/ui/kit";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, fmtNum } from "@/lib/format";
import type { Campaign, OldCode, RGSettings } from "@/lib/review-growth";
import { DEFAULT_QR_STYLE, type Location, type QRStyle, type QRStyleInfo } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { RequestTemplates } from "@/components/review-growth/RequestTemplates";

type Confirm = null | "rotate" | "archive" | "delete" | "design" | "deactivate";
const DEACTIVATE_WORD = "DEACTIVATE";
const dl = "inline-flex min-h-11 items-center gap-1.5 rounded-lg border border-ink-200 bg-white px-3 text-[13px] font-medium hover:bg-ink-50 sm:min-h-8";

export default function CampaignDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const toast = useToast();
  const { isAdmin, role, tenant } = useAuth();
  const { data: c, error, reload, setData } = useFetch<Campaign>(`/review-growth/campaigns/${id}`);
  const settings = useFetch<RGSettings>("/review-growth/settings");
  const locations = useFetch<Location[]>(isAdmin ? "/locations" : null);
  const brand = useFetch<QRStyleInfo>(isAdmin ? "/qr/style" : null);
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState<string | null>(null);
  const [dest, setDest] = useState<string | null>(null);
  const [destError, setDestError] = useState<string | null>(null);
  const [typed, setTyped] = useState("");
  const [modalError, setModalError] = useState<string | null>(null);
  const [design, setDesign] = useState<QRStyle>(DEFAULT_QR_STYLE);
  const [qrVersion, setQrVersion] = useState(0);
  const [target, setTarget] = useState<OldCode | null>(null);

  const close = () => { setConfirm(null); setTyped(""); setModalError(null); };

  /** PATCH never changes the campaign's link or QR code: only its name, state, look and where it leads. */
  async function patch(body: Record<string, unknown>, msg: string, onError?: (m: string) => void): Promise<boolean> {
    setBusy(true);
    try { setData(await api<Campaign>(`/review-growth/campaigns/${id}`, { method: "PATCH", body })); toast(msg); setName(null); setQrVersion((v) => v + 1); return true; }
    catch (e) { const m = errorMessage(e); if (onError) onError(m); else toast(m, "error"); return false; } finally { setBusy(false); }
  }
  /** Issues a new code. The previous one is kept and keeps working, so nothing printed is invalidated. */
  async function rotate() {
    setBusy(true); setModalError(null);
    try {
      setData(await api<Campaign>(`/review-growth/campaigns/${id}/regenerate-qr`, { method: "POST" }));
      setQrVersion((v) => v + 1); close(); toast("New QR code issued. The earlier code still works.");
    } catch (e) {
      setModalError(e instanceof ApiError && e.status === 409 ? errorMessage(e) : e instanceof ApiError && e.status === 403 ? "Only owners and admins can issue a new QR code." : errorMessage(e));
    } finally { setBusy(false); }
  }
  /** The only action that stops a printed code while the campaign is live. Needs the typed word. */
  async function deactivateOld() {
    if (!target || typed.trim() !== DEACTIVATE_WORD) return;
    setBusy(true); setModalError(null);
    try {
      setData(await api<Campaign>(`/review-growth/campaigns/${id}/codes/${target.public_id}/deactivate`, { method: "POST", body: { confirm: DEACTIVATE_WORD } }));
      close(); setTarget(null); toast("That earlier code is switched off. Printed copies of it no longer work.");
    } catch (e) {
      setModalError(e instanceof ApiError && e.status === 404 ? "That code no longer belongs to this campaign. Refresh the page." : e instanceof ApiError && e.status === 403 ? "Only owners and admins can switch a code off." : errorMessage(e));
    } finally { setBusy(false); }
  }
  async function reactivateOld(o: OldCode) {
    setBusy(true);
    try { setData(await api<Campaign>(`/review-growth/campaigns/${id}/codes/${o.public_id}/reactivate`, { method: "POST" })); toast("That earlier code works again."); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); }
  }
  async function remove(permanent: boolean) {
    setBusy(true); setModalError(null);
    try {
      await api(`/review-growth/campaigns/${id}`, { method: "DELETE", params: permanent ? { permanent: "true" } : undefined });
      toast(permanent ? "Campaign and its data deleted." : "Campaign archived."); close();
      if (permanent) router.replace("/gbp/campaigns"); else void reload();
    } catch (e) { setModalError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function saveDesign(next: QRStyle | null) {
    setModalError(null);
    if (await patch({ qr_style: next }, next ? "Design saved for this campaign. The code still opens the same page." : "This campaign now uses your business design.", setModalError)) close();
  }

  if (error) return <Alert tone="error" title="Couldn't load this campaign">{error} <Link href="/gbp/campaigns" className="font-semibold underline">Back to campaigns</Link></Alert>;
  if (!c) return <Skeleton className="h-96" />;

  const loc = settings.data?.locations.find((l) => l.id === c.location_id);
  const archived = c.status === "archived";
  const cz = c.customization;
  const place = [c.location_name].filter(Boolean).join("");
  const targets = (locations.data ?? []).filter((l) => l.is_active || l.id === c.location_id);
  const chosen = dest ?? c.location_id ?? "";
  const qr = (fmt: string) => `${API_V1}/review-growth/campaigns/${c.id}/qr.${fmt}`;

  return (
    <>
      <Link href="/gbp/campaigns" className="mb-3 inline-flex min-h-11 items-center gap-1.5 text-sm font-medium text-ink-500 hover:text-ink sm:min-h-8"><ArrowLeft className="h-4 w-4" aria-hidden />All campaigns</Link>
      <PageHeader eyebrow="QR campaign" title={c.name} subtitle={`${c.location_name ?? "Location removed"} · created ${fmtDate(c.created_at)}`}
        actions={<>
          <StatusBadge status={c.status} />
          {isAdmin && !archived && (c.status === "active"
            ? <Button size="sm" variant="secondary" icon={<Pause className="h-4 w-4" />} loading={busy} onClick={() => void patch({ status: "paused" }, "Campaign paused. The same QR code works again when you resume.")}>Pause</Button>
            : <Button size="sm" icon={<Play className="h-4 w-4" />} loading={busy} onClick={() => void patch({ status: "active" }, "Campaign is live.")}>Resume</Button>)}
          {isAdmin && archived && <Button size="sm" icon={<RotateCcw className="h-4 w-4" />} loading={busy} onClick={() => void patch({ status: "active" }, "Campaign restored. Its QR code works again.")}>Restore</Button>}
        </>} />

      {!c.location_id && !archived && <div className="mb-4"><Alert tone="error" title="This code leads nowhere">Its location was removed, so people who scan it see an inactive page. Choose a location below to bring the same printed code back.</Alert></div>}
      {!c.review_url_ready && !archived && c.location_id && <div className="mb-4"><Alert tone="warning" title="No Google review link for this location">Customers can finish their review but can&rsquo;t continue to Google. Add the link below.</Alert></div>}
      {c.status === "paused" && <div className="mb-4"><Alert tone="info" title="Paused">Anyone scanning the QR code sees that this page is no longer active. Resume to turn the same code back on.</Alert></div>}

      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        <div className="space-y-4">
          <Panel title="QR code" meta="print it, stick it, put it on a table card">
            <div className="grid gap-5 sm:grid-cols-[200px_1fr]">
              <div className="mx-auto grid h-[200px] w-[200px] place-items-center rounded-xl border border-ink-100 bg-white p-2">
                {isAdmin && !archived
                  ? /* eslint-disable-next-line @next/next/no-img-element */ <img key={`${c.public_id}-${qrVersion}`} src={`${qr("svg")}?v=${qrVersion}`} alt={`QR code that opens the ${c.name} review page`} className="h-full w-full object-contain" />
                  : <p className="px-3 text-center text-sm text-ink-500">{archived ? "Restore this campaign to use its QR code." : "Only owners and admins can download QR codes."}</p>}
              </div>
              <div className="min-w-0 space-y-3">
                <div><p className="text-[13px] font-medium text-ink-500">Permanent link (what the code opens)</p>
                  <p className="mt-0.5 break-all rounded-lg bg-ink-50 px-3 py-2 font-mono text-[13px]">{c.url}</p></div>
                <div className="flex flex-wrap gap-2">
                  <CopyButton value={c.url} label="Copy link" />
                  {!archived && <a href={c.url} target="_blank" rel="noopener noreferrer" className={dl}><ExternalLink className="h-4 w-4" aria-hidden />Open page</a>}
                </div>
                {isAdmin && !archived && (
                  <div className="flex flex-wrap gap-2 border-t border-ink-100 pt-3">
                    <a href={qr("png")} download className="inline-flex min-h-11 items-center gap-1.5 rounded-lg bg-fq px-3 text-[13px] font-semibold text-pure-ink hover:bg-fq-hover sm:min-h-8"><Download className="h-4 w-4" aria-hidden />PNG</a>
                    <a href={qr("svg")} download className={dl}><Download className="h-4 w-4" aria-hidden />SVG</a>
                    <a href={qr("pdf")} download className={dl}><Download className="h-4 w-4" aria-hidden />PDF</a>
                    <PosterDownload path={`/review-growth/campaigns/${c.id}/poster`} filename={`flowqr-${c.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "campaign"}`} label="Poster" />
                    <Button size="sm" variant="secondary" icon={<Paintbrush className="h-4 w-4" />} onClick={() => { setDesign(c.qr_style ?? brand.data?.style ?? DEFAULT_QR_STYLE); setModalError(null); setConfirm("design"); }}>Design</Button>
                  </div>)}
                <p className="text-xs text-ink-500">PNG for documents and screens; SVG and PDF stay sharp at any print size. {c.qr_style ? "This campaign has its own design." : <>Drawn in your <Link href="/gbp/cards/designs" className="font-medium text-brand-700 hover:underline">business QR design</Link>.</>} Changing the design or downloading again never changes the link.</p>
              </div>
            </div>
          </Panel>

          <Panel title="Performance" meta="all time">
            <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-5">
              {([["QR scans", c.stats.scans], ["Unique scans", c.stats.unique_scans ?? 0], ["Feedback submitted", c.stats.feedback_submitted], ["Drafts approved", c.stats.drafts_approved], ["Continued to Google", c.stats.google_redirects]] as const).map(([k, v]) => (
                <div key={k}><dt className="text-[13px] text-ink-500">{k}</dt><dd className="num mt-1 text-2xl font-bold leading-none">{fmtNum(v)}</dd></div>))}
            </dl>
            <p className="mt-4 text-xs text-ink-500">Unique scans count different devices per day (FlowQR keeps no identity for them). &ldquo;Continued to Google&rdquo; is a tap, not a published review. <Link href="/analytics/campaigns" className="font-medium text-brand-700 hover:underline">See the full funnel</Link></p>
          </Panel>

          {isAdmin && !archived && (
            <Panel title="Where this code leads" meta="change it any time; the printed code stays the same">
              {destError && <div className="mb-3"><Alert tone="error" title="Destination not changed">{destError}</Alert></div>}
              <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); setDestError(null); if (chosen && chosen !== c.location_id) void patch({ location_id: chosen }, "Destination changed. The same printed code now opens the new location's page.", setDestError).then((ok) => { if (ok) { setDest(null); void settings.reload(); } }); }}>
                <Select label="Location" wrapperClassName="min-w-[220px] flex-1" value={chosen} onChange={(e) => { setDest(e.target.value); setDestError(null); }} disabled={locations.loading && !locations.data}>
                  {!c.location_id && <option value="">Choose a location…</option>}
                  {targets.map((l) => <option key={l.id} value={l.id}>{l.name}{l.is_active ? "" : " (deactivated)"}</option>)}
                </Select>
                <Button type="submit" variant="secondary" icon={<MapPin className="h-4 w-4" />} loading={busy} disabled={!chosen || chosen === c.location_id}>Change destination</Button>
              </form>
              {locations.error && <p className="mt-2 text-xs text-red-700">{locations.error}</p>}
              <p className="mt-3 text-xs text-ink-500">Scans recorded so far stay counted under the location the code led to at the time.</p>
            </Panel>)}

          {isAdmin && !archived && c.location_id && (
            <Panel title="Google review link" meta={loc?.name ?? c.location_name ?? undefined}>
              {loc ? <ReviewLinkEditor locationId={loc.id} current={loc.review_url} source={loc.review_url_source} googleAvailable={loc.google_link_available} onSaved={() => { void settings.reload(); void reload(); }} />
                : <Skeleton className="h-24" />}
              <p className="mt-3 text-xs text-ink-500">Applies to every campaign at this location. FlowQR never posts reviews for customers; it only sends them to this link.</p>
            </Panel>)}

          {isAdmin && (
            <Panel title="Manage">
              <div className="space-y-4">
                {!archived && (
                  <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); if (name && name.trim().length >= 2) void patch({ name: name.trim() }, "Renamed."); }}>
                    <Input label="Campaign name" wrapperClassName="min-w-[220px] flex-1" maxLength={120} value={name ?? c.name} onChange={(e) => setName(e.target.value)} />
                    <Button type="submit" variant="secondary" loading={busy} disabled={name === null || name.trim() === c.name || name.trim().length < 2}>Rename</Button>
                  </form>)}
                <div className="flex flex-wrap gap-2 border-t border-ink-100 pt-4">
                  <Link href={`/gbp/campaigns/landing?c=${c.id}`} className={dl}><Palette className="h-4 w-4" aria-hidden />Customize page</Link>
                  <Link href={`/reputation/assistant?c=${c.id}`} className={dl}><Sparkles className="h-4 w-4" aria-hidden />AI settings</Link>
                </div>
              </div>
            </Panel>)}

          {!archived && <RequestTemplates campaignId={c.id} canEdit={isAdmin} />}

          {isAdmin && !archived && (
            <Panel title="QR codes for this campaign" meta="earlier codes keep working">
              <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span className="min-w-0 flex-1"><b>Issue a new code</b> <span className="text-ink-500">Gives this campaign a fresh link and QR. Codes you have already printed keep working.</span></span>
                <Button size="sm" variant="secondary" icon={<RotateCcw className="h-4 w-4" />} onClick={() => { setModalError(null); setConfirm("rotate"); }}>Issue new code</Button>
              </div>
              {c.old_codes.length > 0 && (
                <div className="mt-4 border-t border-ink-100 pt-3">
                  <p className="mb-2 text-[13px] font-medium text-ink-500">Earlier codes ({c.old_codes.length})</p>
                  <ul className="divide-y divide-ink-100 rounded-lg border border-ink-100" aria-label="Earlier codes">
                    {c.old_codes.map((o) => (
                      <li key={o.public_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2">
                        <span className="min-w-0 flex-1"><span className="block break-all font-mono text-xs">{o.url}</span>
                          <span className="text-xs text-ink-500">in use until {fmtDate(o.retired_at)} · {o.active ? "still works, opens this campaign" : `switched off ${o.deactivated_at ? fmtDate(o.deactivated_at) : ""}`}</span></span>
                        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${o.active ? "bg-green-50 text-green-800" : "bg-red-50 text-red-800"}`}>{o.active ? "Working" : "Switched off"}</span>
                        {o.active
                          ? <Button size="sm" variant="danger" onClick={() => { setTarget(o); setTyped(""); setModalError(null); setConfirm("deactivate"); }}>Switch off…</Button>
                          : <Button size="sm" variant="secondary" loading={busy} onClick={() => void reactivateOld(o)}>Switch back on</Button>}
                      </li>))}
                  </ul>
                </div>)}
            </Panel>)}

          {isAdmin && (
            <Panel title="Actions that stop this campaign's codes" meta="each one asks first">
              <ul className="space-y-3 text-sm">
                {!archived && <li className="flex flex-wrap items-center justify-between gap-2"><span className="min-w-0 flex-1"><b>Archive</b> <span className="text-ink-500">Stops every code of this campaign until you restore it. Statistics are kept.</span></span>
                  <Button size="sm" variant="secondary" onClick={() => { setModalError(null); setConfirm("archive"); }}>Archive</Button></li>}
                {archived && role === "owner" && <li className="flex flex-wrap items-center justify-between gap-2"><span className="min-w-0 flex-1"><b>Delete permanently</b> <span className="text-ink-500">Erases the campaign, all its codes and all its data.</span></span>
                  <Button size="sm" variant="danger" icon={<Trash2 className="h-4 w-4" />} onClick={() => { setModalError(null); setConfirm("delete"); }}>Delete permanently</Button></li>}
                {archived && role !== "owner" && <li className="text-ink-500">Only the owner can permanently delete an archived campaign.</li>}
              </ul>
            </Panel>)}
        </div>

        <aside aria-label="Live preview of the customer page" className="lg:sticky lg:top-6 lg:self-start">
          <p className="mb-2 text-[13px] font-medium text-ink-500">What customers see</p>
          <div className="mx-auto h-[540px] w-[300px] overflow-y-auto overflow-x-hidden rounded-[30px] border-[7px] border-ink bg-white shadow-float">
            <LandingFrame preview business={{ name: cz.display_name ?? tenant?.name ?? "Your business", logo_url: cz.logo_url ?? tenant?.logo_url ?? null, location: place }} branding={{ brand_color: cz.brand_color, background: cz.background, welcome_message: cz.welcome_message, footer_message: cz.footer_message }}>
              <PreviewForm />
            </LandingFrame>
          </div>
          <KV className="mt-4" rows={[["Language", cz.default_language === "hi" ? "Hindi (default)" : "English (default)"], ["Writing style", cz.default_style], ["Star rating", "Asked on the page (needed for AI help, optional for writing it yourself)"]]} />
        </aside>
      </div>

      <Modal open={confirm === "rotate"} onClose={close} title="Issue a new QR code?"
        footer={<><Button variant="secondary" onClick={close}>Cancel</Button><Button loading={busy} onClick={() => void rotate()}>Issue new code</Button></>}>
        <div className="space-y-3 text-sm">
          <p>This campaign gets a new link and QR code for future printing. <b>Copies of the current code that are already printed keep working</b> and open the same page.</p>
          <p>You don&rsquo;t need a new code to change the location, the Google link, the design or the landing page.</p>
          <p className="text-ink-500">If the current code leaked, issue a new one here, then switch the old one off in the list of earlier codes.</p>
          {modalError && <Alert tone="error" title="No new code was issued">{modalError}</Alert>}
        </div>
      </Modal>
      <Modal open={confirm === "deactivate"} onClose={() => { close(); setTarget(null); }} title="Switch this earlier code off?"
        footer={<><Button variant="secondary" onClick={() => { close(); setTarget(null); }}>Keep it working</Button><Button variant="danger" loading={busy} disabled={typed.trim() !== DEACTIVATE_WORD} onClick={() => void deactivateOld()}>Switch the code off</Button></>}>
        <div className="space-y-3 text-sm">
          <div className="flex gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-red-900"><TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <p><b>Every printed or shared copy of this code will stop working.</b> People who scan it will see that the code was switched off.</p></div>
          {target && <p className="break-all rounded-lg bg-ink-50 px-3 py-2 font-mono text-xs">{target.url}</p>}
          <p>The campaign&rsquo;s current code and its other earlier codes are not affected. You can switch this code back on later.</p>
          {modalError && <Alert tone="error" title="The code was not switched off">{modalError}</Alert>}
          <Input label={`Type ${DEACTIVATE_WORD} to confirm`} value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" autoCapitalize="characters" />
        </div>
      </Modal>
      <Modal open={confirm === "archive"} onClose={close} title="Archive this campaign?"
        footer={<><Button variant="secondary" onClick={close}>Cancel</Button><Button variant="danger" loading={busy} onClick={() => void remove(false)}>Archive</Button></>}>
        <div className="space-y-3 text-sm"><p><b>Every printed QR code of this campaign stops working</b> while it is archived: people who scan one see an inactive page. Restoring the campaign brings the same codes back. Statistics are kept.</p>
          {modalError && <Alert tone="error" title="Not archived">{modalError}</Alert>}</div>
      </Modal>
      <Modal open={confirm === "delete"} onClose={close} title="Delete permanently?"
        footer={<><Button variant="secondary" onClick={close}>Cancel</Button><Button variant="danger" loading={busy} onClick={() => void remove(true)}>Delete campaign and data</Button></>}>
        <div className="space-y-3 text-sm"><p>This erases the campaign, its statistics and every customer session and draft. <b>Its printed QR codes, current and earlier, will never work again, and it can&rsquo;t be undone.</b></p>
          {modalError && <Alert tone="error" title="Not deleted">{modalError}</Alert>}</div>
      </Modal>
      <Modal open={confirm === "design"} onClose={close} title="QR design for this campaign"
        footer={<>
          {c.qr_style && <Button variant="ghost" className="mr-auto" disabled={busy} onClick={() => void saveDesign(null)}>Use business design</Button>}
          <Button variant="secondary" onClick={close}>Cancel</Button><Button loading={busy} disabled={!!styleProblem(design)} onClick={() => void saveDesign(design)}>Save design</Button></>}>
        <div className="space-y-4">
          <p className="text-sm text-ink-500">Only the look changes. The code keeps opening the same permanent link, so printed copies stay valid.</p>
          {modalError && <Alert tone="error" title="Design not saved">{modalError}</Alert>}
          <QrPreview value={design} />
          <QrStyleEditor value={design} onChange={(v) => { setDesign(v); setModalError(null); }} hasLogo={brand.data?.has_logo ?? false} />
        </div>
      </Modal>
    </>
  );
}
