"use client";
import { Plus } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input, Select, Textarea } from "@/components/ui/Form";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import { audienceWords, campaignBlockers, CAMPAIGN_STATUS, reasonWords, rupees, type WaCampaign, type WaCampaignPreview, type WaCampaignResults, type WaTemplates } from "@/lib/whatsapp";

const OFFER_MAX = 120;

/** Offers: a message to customers who agreed to receive offers. You see who and the likely WhatsApp charge first, and nothing is sent until you approve. */
export default function Offers() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const list = useFetch<{ items: WaCampaign[]; allowed: boolean; sending: boolean }>("/whatsapp/campaigns");
  const tpl = useFetch<WaTemplates>("/whatsapp/templates");
  const [creating, setCreating] = useState(false), [open, setOpen] = useState<string | null>(null), [busy, setBusy] = useState(false);
  const offer = tpl.data?.items.find((t) => t.key === "offer");

  async function prepare() {
    setBusy(true);
    try { await api("/whatsapp/templates/install", { method: "POST", body: { key: "offer" } }); toast("Offer message sent to WhatsApp for approval."); await tpl.reload(); } catch (e) { toast(errorMessage(e)); } finally { setBusy(false); }
  }
  async function check() {
    setBusy(true);
    try { await api("/whatsapp/templates/sync", { method: "POST" }); await tpl.reload(); } catch (e) { toast(errorMessage(e)); } finally { setBusy(false); }
  }

  return (
    <>
      <PageHeader title="Offers" subtitle="Send an offer to customers who agreed to receive them. You approve it before anything is sent."
        actions={isAdmin && list.data?.allowed && offer?.status === "approved" ? <Button variant="brand" icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>New offer</Button> : undefined} />
      {list.error && <Alert tone="error">{list.error}</Alert>}
      {!list.data || !tpl.data ? <Skeleton className="h-64" /> : (
        <div className="space-y-4">
          {!list.data.allowed && <Alert tone="info" title="Part of the Growth and Pro add-ons">Offers are not included in your WhatsApp add-on. Ask the FlowQR team to upgrade it.</Alert>}
          {list.data.allowed && !offer && <Alert tone="info" title="First, get the offer message approved" action={isAdmin ? <Button loading={busy} onClick={() => void prepare()}>Prepare the message</Button> : undefined}>WhatsApp has to approve the wording of every message. We send it for you. It usually takes a short while.</Alert>}
          {offer && offer.status !== "approved" && <Alert tone={offer.status === "rejected" ? "warning" : "info"} title={offer.status === "pending" ? "WhatsApp is reviewing the offer message" : "The offer message is not approved"} action={<Button variant="secondary" loading={busy} onClick={() => void check()}>Check again</Button>}>{offer.rejection_reason ? `Reason: ${offer.rejection_reason}` : "You can create offers as soon as it is approved."}</Alert>}
          {!list.data.sending && <Alert tone="info">Sending is not switched on yet. You can prepare and approve offers now. They start when FlowQR switches WhatsApp sending on.</Alert>}
          {list.data.items.length === 0 ? <EmptyState title="No offers yet">Offers go only to customers who agreed to receive them.</EmptyState> : (
            <div className="space-y-3">{list.data.items.map((c) => (
              <Card key={c.id}>
                <button type="button" onClick={() => setOpen(c.id)} className="flex w-full flex-wrap items-start justify-between gap-3 text-left">
                  <span className="min-w-0"><span className="block font-semibold text-ink">{c.name}</span><span className="mt-0.5 block text-[13px] text-ink-500">{c.variables.offer_text} · {fmtDate(c.created_at)}</span></span>
                  <Badge tone={CAMPAIGN_STATUS[c.status].tone}>{CAMPAIGN_STATUS[c.status].label}</Badge>
                </button>
              </Card>))}</div>
          )}
        </div>
      )}
      {creating && offer && <NewOffer templateId={offer.id} onClose={() => setCreating(false)} onDone={(id) => { setCreating(false); void list.reload(); setOpen(id); }} />}
      {open && <OfferDetail id={open} canEdit={isAdmin} onClose={() => { setOpen(null); void list.reload(); }} />}
    </>
  );
}

function NewOffer({ templateId, onClose, onDone }: { templateId: string; onClose: () => void; onDone: (id: string) => void }) {
  const [f, setF] = useState({ name: "", offer: "", kind: "all", tag: "", days: "30" });
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const aud = f.kind === "tag" ? { kind: "tag", tag: f.tag.trim() } : f.kind === "new" || f.kind === "existing" ? { kind: f.kind, days: Number(f.days) } : { kind: "all" };
  const ok = f.name.trim().length >= 2 && f.offer.trim().length >= 5 && f.offer.length <= OFFER_MAX && (f.kind !== "tag" || f.tag.trim().length > 0);
  async function save() {
    setBusy(true); setErr(null);
    try { const c = await api<WaCampaign>("/whatsapp/campaigns", { method: "POST", body: { name: f.name.trim(), template_id: templateId, audience: aud, variables: { offer_text: f.offer.trim() } } }); onDone(c.id); }
    catch (e) { setErr(errorMessage(e)); setBusy(false); }
  }
  return (
    <Modal open onClose={onClose} title="New offer" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant="brand" loading={busy} disabled={!ok} onClick={() => void save()}>Save and review</Button></>}>
      <div className="space-y-4">
        {err && <Alert tone="error">{err}</Alert>}
        <Input label="Name (only you see this)" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Diwali offer" />
        <Textarea label="Your offer" rows={2} maxLength={OFFER_MAX} value={f.offer} onChange={(e) => setF({ ...f, offer: e.target.value })} hint={`${f.offer.length}/${OFFER_MAX}. For example: 10% off all sessions this week.`} />
        <Select label="Who should get it?" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
          <option value="all">Everyone who agreed to receive offers</option><option value="tag">A group of customers</option><option value="new">New customers</option><option value="existing">Earlier customers</option>
        </Select>
        {f.kind === "tag" && <Input label="Group name" value={f.tag} onChange={(e) => setF({ ...f, tag: e.target.value })} hint="The group you gave customers when you added them, for example: regular." />}
        {(f.kind === "new" || f.kind === "existing") && <Input label="Days" type="number" min={1} max={365} value={f.days} onChange={(e) => setF({ ...f, days: e.target.value })} hint={f.kind === "new" ? "Customers added in the last this many days." : "Customers added more than this many days ago."} />}
        <p className="text-[13px] text-ink-500">Only customers who agreed to receive offers, and have not asked to stop, are ever included.</p>
      </div>
    </Modal>
  );
}

function OfferDetail({ id, canEdit, onClose }: { id: string; canEdit: boolean; onClose: () => void }) {
  const toast = useToast();
  const pv = useFetch<WaCampaignPreview>(`/whatsapp/campaigns/${id}`);
  const started = !!pv.data && ["sending", "paused", "done", "cancelled"].includes(pv.data.status);
  const res = useFetch<WaCampaignResults>(started ? `/whatsapp/campaigns/${id}/results` : null);
  const [seen, setSeen] = useState(false), [busy, setBusy] = useState<string | null>(null), [err, setErr] = useState<string | null>(null);
  const p = pv.data;
  const blockers = p ? campaignBlockers(p) : [];

  async function approve() {
    if (!p) return;
    setBusy("approve"); setErr(null);
    try { await api(`/whatsapp/campaigns/${id}/approve`, { method: "POST", body: { confirm_recipients: p.recipients, accept_estimate: true } }); toast("Approved. It will start shortly."); setSeen(false); await pv.reload(); }
    catch (e) { setErr(errorMessage(e)); await pv.reload(); } finally { setBusy(null); }
  }
  async function act(a: "pause" | "resume" | "cancel") {
    setBusy(a); setErr(null);
    try { await api(`/whatsapp/campaigns/${id}/${a}`, { method: "POST" }); await pv.reload(); await res.reload(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(null); }
  }
  return (
    <Modal open onClose={onClose} title={p?.name ?? "Offer"} footer={<Button variant="secondary" onClick={onClose}>Close</Button>}>
      {!p ? <Skeleton className="h-40" /> : (
        <div className="space-y-4 text-sm">
          {err && <Alert tone="error">{err}</Alert>}
          <div className="flex items-center gap-2"><Badge tone={CAMPAIGN_STATUS[p.status].tone}>{CAMPAIGN_STATUS[p.status].label}</Badge><span className="text-ink-500">{audienceWords(p.audience)}</span></div>
          {p.message_preview && <div><p className="mb-1 text-[13px] font-semibold text-ink-500">What customers will read</p><p className="rounded-2xl bg-surface-2 p-4 text-ink">{p.message_preview}</p></div>}
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-2xl bg-surface-2 p-4"><p className="text-[13px] text-ink-500">Customers who will get it</p><p className="mt-1 text-2xl font-semibold tabular-nums text-ink">{p.status === "draft" || p.status === "paused" ? p.recipients : p.approved_recipients ?? p.recipients}</p></div>
            <div className="rounded-2xl bg-surface-2 p-4"><p className="text-[13px] text-ink-500">Likely WhatsApp charge</p><p className="mt-1 text-2xl font-semibold tabular-nums text-ink">{rupees(p.status === "draft" ? p.estimate.amount : p.approved_cost ?? p.estimate.amount)}</p></div>
          </div>
          <p className="text-[13px] text-ink-500">{p.estimate.note} {p.excluded_note}</p>
          {p.status === "draft" && canEdit && (
            <div className="space-y-3 border-t border-line pt-3">
              {blockers.length > 0 ? <Alert tone="info" title="Not ready yet"><ul className="list-disc pl-5">{blockers.map((b) => <li key={b}>{b}</li>)}</ul></Alert> : (
                <>
                  <label className="flex items-start gap-3 text-ink-700"><input type="checkbox" checked={seen} onChange={(e) => setSeen(e.target.checked)} className="mt-1 h-4 w-4 accent-[#BD3E1B]" /><span>I have seen that this goes to <b>{p.recipients}</b> customers and may cost about <b>{rupees(p.estimate.amount)}</b> in WhatsApp charges.</span></label>
                  <Button variant="brand" disabled={!seen} loading={busy === "approve"} onClick={() => void approve()}>Approve and send</Button>
                  {!p.ready.sending_on && <p className="text-[13px] text-ink-500">Sending is not switched on yet. It starts when FlowQR switches it on.</p>}
                </>
              )}
            </div>
          )}
          {canEdit && ["scheduled", "sending"].includes(p.status) && <div className="flex gap-2"><Button variant="secondary" loading={busy === "pause"} onClick={() => void act("pause")}>Pause</Button><Button variant="ghost" loading={busy === "cancel"} onClick={() => void act("cancel")}>Cancel</Button></div>}
          {canEdit && p.status === "paused" && <div className="flex gap-2"><Button variant="brand" loading={busy === "resume"} onClick={() => void act("resume")}>Resume</Button><Button variant="ghost" loading={busy === "cancel"} onClick={() => void act("cancel")}>Cancel</Button></div>}
          {res.data && (
            <div className="border-t border-line pt-3">
              <p className="mb-2 font-semibold text-ink">Results so far</p>
              <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {([["Sent", res.data.sent], ["Delivered", res.data.delivered], ["Read", res.data.read], ["Not delivered", res.data.failed], ["Waiting", res.data.waiting], ["Not sent", res.data.skipped], ["Asked to stop after", res.data.opted_out_after], ["Charge so far", rupees(res.data.estimated_meta_cost)]] as [string, number | string][]).map(([l, v]) => <div key={l} className="rounded-xl bg-surface-2 p-3"><dt className="text-[12px] text-ink-500">{l}</dt><dd className="font-semibold tabular-nums text-ink">{v}</dd></div>)}
              </dl>
              {Object.keys(res.data.skipped_reasons).length > 0 && <ul className="mt-2 list-disc pl-5 text-[13px] text-ink-700">{Object.entries(res.data.skipped_reasons).map(([r, n]) => <li key={r}>{n}: {reasonWords(r)}</li>)}</ul>}
              <p className="mt-2 text-[13px] text-ink-500">{res.data.note}</p>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
