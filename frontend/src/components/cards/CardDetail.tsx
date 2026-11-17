"use client";
import { Check, Copy, ExternalLink, Nfc } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Skeleton } from "@/components/ui/Card";
import { Input, Textarea } from "@/components/ui/Form";
import { Segmented } from "@/components/ui/kit";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { API_V1 } from "@/lib/config";
import { STATUS_TONE } from "@/lib/card-ui";
import { fmtDate, fmtNum } from "@/lib/format";
import type { Card as CardT } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

type Tab = "overview" | "destination" | "nfc" | "analytics";

interface Detail { card: CardT; history: { tenant: string; location: string | null; campaign: string | null; assigned_at: string; unassigned_at: string | null; ended_reason: string | null }[] }
interface Dest { url: string | null; set_at: string | null; live: boolean; history: { action: string; old_url: string | null; new_url: string | null; reason: string | null; changed_by: string | null; changed_at: string }[] }
interface Nfc { nfc_url: string; qr_url: string; status: "not_programmed" | "marked_programmed" | "tap_seen"; programmed_at: string | null; last_tap_at: string | null; note: string; pairing: string; instructions: string[] }
interface Stats {
  days: number; totals: { qr_scans: number; nfc_taps: number; untracked: number; total: number; unique_visitors: number }; automated_visits: number; devices: Record<string, number>;
  referrers: { host: string; scans: number }[]; placements: { placement: string; scans: number }[]; last_scan_at: string | null; last_nfc_tap_at: string | null; note: string;
}

function CopyField({ label, value }: { label: string; value: string }) {
  const [done, setDone] = useState(false);
  async function copy() { try { await navigator.clipboard.writeText(value); setDone(true); setTimeout(() => setDone(false), 2000); } catch { /* the address is selectable as text */ } }
  return (
    <div>
      <p className="text-xs font-semibold text-ink-700">{label}</p>
      <div className="mt-1 flex items-stretch gap-2">
        <p className="min-w-0 flex-1 break-all rounded-xl bg-surface-2 p-3 font-mono text-xs leading-5 text-ink">{value}</p>
        <Button variant="secondary" size="sm" className="!rounded-xl" aria-label={`Copy ${label}`} onClick={() => void copy()} icon={done ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}>{done ? "Copied" : "Copy"}</Button>
      </div>
    </div>
  );
}

const NFC_STATE: Record<Nfc["status"], { tone: "gray" | "amber" | "green"; label: string; help: string }> = {
  not_programmed: { tone: "gray", label: "Not programmed", help: "No tag has been marked as written for this card." },
  marked_programmed: { tone: "amber", label: "Marked as programmed", help: "An administrator says the tag was written. No tap has confirmed it yet: tap the tag with a phone to check." },
  tap_seen: { tone: "green", label: "Tap confirmed", help: "A real NFC tap has opened this card since it was marked programmed." },
};

function Tile({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return <div className="rounded-2xl bg-surface-2 px-3 py-2.5"><p className="num font-display text-xl font-semibold leading-6 text-ink">{value}</p><p className="mt-0.5 text-[11.5px] leading-4 text-muted">{label}</p>{hint && <p className="mt-0.5 text-[11px] text-muted">{hint}</p>}</div>;
}

/** One QR/NFC asset: where it points, its NFC tag, and how it is used. Every change here is confirmed when the card is live, audited, and needs no new QR and no tag rewrite. */
export function CardDetail({ card, onClose, onChanged }: { card: CardT; onClose: () => void; onChanged: () => void }) {
  const toast = useToast();
  const [tab, setTab] = useState<Tab>("overview");
  const detail = useFetch<Detail>(`/admin/cards/${card.id}`);
  const dest = useFetch<Dest>(tab === "destination" || tab === "overview" ? `/admin/cards/${card.id}/destination` : null);
  const nfc = useFetch<Nfc>(tab === "nfc" ? `/admin/cards/${card.id}/nfc` : null);
  const stats = useFetch<Stats>(tab === "analytics" ? `/admin/cards/${card.id}/analytics` : null, { days: 30 });
  const [url, setUrl] = useState("");
  const [reason, setReason] = useState("");
  const [checked, setChecked] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const live = card.status === "assigned" || card.status === "active";

  async function check() {
    setBusy("check"); setProblem(null); setChecked(null);
    try { const r = await api<{ url: string }>(`/admin/cards/${card.id}/destination/check`, { method: "POST", body: { url } }); setChecked(r.url); }
    catch (e) { setProblem(errorMessage(e)); } finally { setBusy(null); }
  }
  async function save(confirm = false) {
    setBusy("save"); setProblem(null);
    try {
      await api(`/admin/cards/${card.id}/destination`, { method: "PUT", body: { url, reason: reason || null, confirm } });
      toast("Destination saved. It applies to the next scan or tap: nothing to reprint or reprogram."); setUrl(""); setReason(""); setChecked(null); void dest.reload(); onChanged();
    } catch (e) {
      if (e instanceof ApiError && e.code === "confirmation_required") { if (window.confirm(`${e.message}\n\nContinue?`)) return void save(true); }
      else setProblem(errorMessage(e));
    } finally { setBusy(null); }
  }
  async function clear(confirm = false) {
    setBusy("clear");
    try { await api(`/admin/cards/${card.id}/destination/clear`, { method: "POST", body: { confirm } }); toast("Back to the card's normal review page."); void dest.reload(); onChanged(); }
    catch (e) { if (e instanceof ApiError && e.code === "confirmation_required") { if (window.confirm(`${e.message}\n\nContinue?`)) return void clear(true); } else toast(errorMessage(e), "error"); }
    finally { setBusy(null); }
  }
  async function mark(programmed: boolean) {
    setBusy("nfc");
    try { await api(`/admin/cards/${card.id}/nfc`, { method: "POST", body: { programmed } }); toast(programmed ? "Marked as programmed. Tap the tag to confirm it works." : "Mark removed."); void nfc.reload(); onChanged(); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); }
  }

  const c = detail.data?.card ?? card;
  return (
    <Modal open onClose={onClose} title={card.card_code} footer={<Button variant="secondary" className="!rounded-full" onClick={onClose}>Done</Button>}>
      <div className="mb-4 flex flex-wrap items-center gap-2"><Badge tone={STATUS_TONE[c.status]}>{c.status}</Badge>
        <span className="text-sm text-ink-700">{c.tenant_name ? <>{c.tenant_name} · {c.location_name ?? "no location yet"}{c.campaign_name ? ` · ${c.campaign_name}` : ""}{c.label ? ` · ${c.label}` : ""}</> : "In stock: not assigned to a business"}</span></div>
      <Segmented<Tab> label="Section" value={tab} onChange={setTab} options={[["overview", "Overview"], ["destination", "Destination"], ["nfc", "NFC"], ["analytics", "Analytics"]]} className="mb-4" />

      {tab === "overview" && (
        <div className="space-y-4">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <div className="grid place-items-center"><img src={`${API_V1}/admin/cards/${card.id}/qr.svg`} alt={`QR code for ${card.card_code}`} className="h-48 w-48 rounded-2xl border border-line bg-white p-2" /></div>
          <CopyField label="Printed QR address" value={c.url} />
          {c.nfc_url && <CopyField label="NFC tag address" value={c.nfc_url} />}
          <p className="rounded-xl bg-surface-2 p-3 text-xs leading-5 text-muted">Where a scan goes now: <b className="text-ink">{dest.data?.url ?? "the card's review page"}</b>. The printed QR and the NFC address stay the same whatever the destination is.</p>
          {detail.data && detail.data.history.length > 0 && (
            <div><p className="text-xs font-semibold text-ink-700">Assignment history</p>
              <ul className="mt-1.5 divide-y divide-line rounded-xl border border-line text-sm">{detail.data.history.map((h, i) => (
                <li key={i} className="px-3 py-2"><span className="font-medium text-ink">{h.tenant}</span>{h.location ? ` · ${h.location}` : ""}{h.campaign ? ` · ${h.campaign}` : ""}
                  <span className="block text-xs text-muted">{fmtDate(h.assigned_at)}{h.unassigned_at ? ` to ${fmtDate(h.unassigned_at)} (${h.ended_reason ?? "ended"})` : " to now"}</span></li>))}</ul></div>)}
        </div>
      )}

      {tab === "destination" && (
        <div className="space-y-4">
          <p className="text-sm leading-6 text-muted">Send everyone who scans or taps this card somewhere other than its review page. Only secure <b className="text-ink">https://</b> addresses are accepted. Changing it never needs a new QR or a new tag.</p>
          {live && <Alert tone="warning" title="This card is live">A new destination applies to the very next scan or tap. You will be asked to confirm.</Alert>}
          <div className="rounded-2xl bg-surface-2 p-3 text-sm"><p className="text-xs font-semibold text-ink-700">Current destination</p><p className="mt-1 break-all">{dest.data?.url ?? <span className="text-muted">None: the card opens its normal review page</span>}</p>
            {dest.data?.url && <Button className="mt-2 !rounded-full" size="sm" variant="secondary" loading={busy === "clear"} onClick={() => void clear()}>Use the review page again</Button>}</div>
          <Input label="New destination" type="url" inputMode="url" placeholder="https://example.com/where-to-send-people" value={url} onChange={(e) => { setUrl(e.target.value); setChecked(null); setProblem(null); }} />
          <Textarea label="Why (optional, kept in the history)" rows={2} maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} />
          {problem && <Alert tone="error" title="That address can't be used">{problem}</Alert>}
          {checked && <Alert tone="success" title="The address is valid"><span className="break-all">{checked}</span> <a href={checked} target="_blank" rel="noopener noreferrer" className="ml-1 inline-flex items-center gap-1 font-medium underline underline-offset-2">Open it to test <ExternalLink className="h-3.5 w-3.5" aria-hidden /></a><span className="mt-1 block text-xs">FlowQR does not visit the address itself: open it in your own browser to see that it works.</span></Alert>}
          <div className="flex flex-wrap gap-2"><Button variant="secondary" className="!rounded-full" disabled={!url.trim()} loading={busy === "check"} onClick={() => void check()}>Check address</Button>
            <Button className="!rounded-full" disabled={!url.trim()} loading={busy === "save"} onClick={() => void save()}>Save destination</Button></div>
          <div><p className="text-xs font-semibold text-ink-700">History</p>
            {!dest.data ? <Skeleton className="mt-1.5 h-16" /> : dest.data.history.length === 0 ? <p className="mt-1.5 text-sm text-muted">No changes yet.</p> : (
              <ul className="mt-1.5 divide-y divide-line rounded-xl border border-line text-sm">{dest.data.history.map((h, i) => (
                <li key={i} className="px-3 py-2"><span className="font-medium text-ink">{h.action === "set" ? "Set" : "Cleared"}</span> · <span className="text-xs text-muted">{fmtDate(h.changed_at)}{h.changed_by ? ` · ${h.changed_by}` : ""}</span>
                  {h.old_url && <span className="block break-all text-xs text-muted">From: {h.old_url}</span>}{h.new_url && <span className="block break-all text-xs text-muted">To: {h.new_url}</span>}{h.reason && <span className="block text-xs text-ink-700">“{h.reason}”</span>}</li>))}</ul>)}</div>
        </div>
      )}

      {tab === "nfc" && (!nfc.data ? <Skeleton className="h-48" /> : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2"><span className="grid h-8 w-8 place-items-center rounded-xl bg-surface-2 text-ink"><Nfc className="h-4 w-4" aria-hidden /></span>
            <Badge tone={NFC_STATE[nfc.data.status].tone}>{NFC_STATE[nfc.data.status].label}</Badge>{nfc.data.last_tap_at && <span className="text-xs text-muted">Last tap {fmtDate(nfc.data.last_tap_at)}</span>}</div>
          <p className="text-sm text-muted">{NFC_STATE[nfc.data.status].help}</p>
          <CopyField label="NFC address to write (URL record)" value={nfc.data.nfc_url} />
          <p className="text-xs text-muted">Paired QR: <span className="break-all font-mono">{nfc.data.qr_url}</span>. {nfc.data.pairing}.</p>
          <div><p className="text-xs font-semibold text-ink-700">How to program the tag</p><ol className="mt-1.5 list-decimal space-y-1.5 pl-5 text-sm leading-6 text-ink-700">{nfc.data.instructions.map((s) => <li key={s}>{s}</li>)}</ol></div>
          <Alert tone="info">{nfc.data.note}</Alert>
          <div className="flex flex-wrap gap-2">
            {nfc.data.status === "not_programmed" ? <Button className="!rounded-full" loading={busy === "nfc"} onClick={() => void mark(true)}>Mark as programmed</Button>
              : <Button className="!rounded-full" variant="secondary" loading={busy === "nfc"} onClick={() => void mark(false)}>Remove the mark</Button>}
            <a href={nfc.data.nfc_url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center gap-1.5 rounded-full bg-surface-2 px-4 text-sm font-semibold text-ink hover:bg-surface-3">Open the address to test <ExternalLink className="h-4 w-4" aria-hidden /></a>
          </div>
        </div>
      ))}

      {tab === "analytics" && (!stats.data ? <Skeleton className="h-48" /> : (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
            <Tile label="QR scans" value={fmtNum(stats.data.totals.qr_scans)} /><Tile label="NFC taps" value={fmtNum(stats.data.totals.nfc_taps)} /><Tile label="Total visits" value={fmtNum(stats.data.totals.total)} />
            <Tile label="Different visitors" value={fmtNum(stats.data.totals.unique_visitors)} /><Tile label="Automated visits" value={fmtNum(stats.data.automated_visits)} hint="not counted above" />
            {stats.data.totals.untracked > 0 && <Tile label="From before channels were tracked" value={fmtNum(stats.data.totals.untracked)} />}
          </div>
          <p className="text-xs text-muted">Last {stats.data.days} days. {stats.data.last_scan_at ? `Last visit ${fmtDate(stats.data.last_scan_at)}.` : "No visits yet."} {stats.data.note}</p>
          {Object.keys(stats.data.devices).length > 0 && <p className="text-sm text-ink-700"><b>Devices:</b> {Object.entries(stats.data.devices).map(([d, n]) => `${d} ${n}`).join(" · ")}</p>}
          {stats.data.referrers.length > 0 && <p className="text-sm text-ink-700"><b>Came from:</b> {stats.data.referrers.map((r) => `${r.host} ${r.scans}`).join(" · ")}</p>}
          {stats.data.placements.length > 0 && <p className="text-sm text-ink-700"><b>Placement:</b> {stats.data.placements.map((p) => `${p.placement} ${p.scans}`).join(" · ")}</p>}
        </div>
      ))}
    </Modal>
  );
}
