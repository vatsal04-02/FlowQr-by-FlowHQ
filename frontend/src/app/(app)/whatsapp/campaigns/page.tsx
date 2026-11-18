"use client";
import { Copy, Download, Plus } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input, Select, Textarea } from "@/components/ui/Form";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, apiFile, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import {
  audienceSentence, barPercent, blankLabel, campaignBlockers, CAMPAIGN_STATUS, fromIstInput, offerChoices, percent, reasonWords, rupees, toIstInput, windowSentence,
  type WaAudience, type WaCampaign, type WaCampaignPreview, type WaCampaignResults, type WaCompareRow, type WaMapping, type WaStatus, type WaTemplates, type WaVariables,
} from "@/lib/whatsapp";

const OFFER_MAX = 120;
const SOURCE_WORDS = { customer_name: "The customer's first name", business_name: "My business name", text: "Text I write" } as const;
const splitList = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

/** Offers: a message to customers who agreed to receive offers. You see who and the likely WhatsApp charge first, and nothing is sent until you approve. */
export default function Offers() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const list = useFetch<{ items: WaCampaign[]; allowed: boolean; sending: boolean }>("/whatsapp/campaigns");
  const tpl = useFetch<WaTemplates>("/whatsapp/templates");
  const cmp = useFetch<{ items: WaCompareRow[] }>("/whatsapp/campaigns/compare");
  const [creating, setCreating] = useState(false), [open, setOpen] = useState<string | null>(null), [busy, setBusy] = useState(false);
  const offer = tpl.data?.items.find((t) => t.key === "offer");
  const choices = offerChoices(tpl.data?.items ?? []);

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
        actions={isAdmin && list.data?.allowed && choices.length > 0 ? <Button variant="brand" icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>New offer</Button> : undefined} />
      {list.error && <Alert tone="error">{list.error}</Alert>}
      {!list.data || !tpl.data ? <Skeleton className="h-64" /> : (
        <div className="space-y-4">
          {!list.data.allowed && <Alert tone="info" title="Part of the Growth and Pro add-ons">Offers are not included in your WhatsApp add-on. Ask the FlowQR team to upgrade it.</Alert>}
          {list.data.allowed && !offer && <Alert tone="info" title="First, get the offer message approved" action={isAdmin ? <Button loading={busy} onClick={() => void prepare()}>Prepare the message</Button> : undefined}>WhatsApp has to approve the wording of every message. We send it for you. It usually takes a short while.</Alert>}
          {offer && offer.status !== "approved" && choices.length === 0 && <Alert tone={offer.status === "rejected" ? "warning" : "info"} title={offer.status === "pending" ? "WhatsApp is reviewing the offer message" : "The offer message is not approved"} action={<Button variant="secondary" loading={busy} onClick={() => void check()}>Check again</Button>}>{offer.rejection_reason ? `Reason: ${offer.rejection_reason}` : "You can create offers as soon as it is approved."}</Alert>}
          {!list.data.sending && <Alert tone="info">Sending is not switched on yet. You can prepare and approve offers now. They start when FlowQR switches WhatsApp sending on.</Alert>}
          {list.data.items.length === 0 ? <EmptyState title="No offers yet">Offers go only to customers who agreed to receive them.</EmptyState> : (
            <div className="space-y-3">{list.data.items.map((c) => (
              <Card key={c.id}>
                <button type="button" onClick={() => setOpen(c.id)} className="flex w-full flex-wrap items-start justify-between gap-3 text-left">
                  <span className="min-w-0"><span className="block font-semibold text-ink">{c.name}</span><span className="mt-0.5 block text-[13px] text-ink-500">{c.variables.offer_text ?? "Custom message"} · {c.scheduled_at ? `starts ${fmtDate(c.scheduled_at)}` : fmtDate(c.created_at)}</span></span>
                  <Badge tone={CAMPAIGN_STATUS[c.status].tone}>{CAMPAIGN_STATUS[c.status].label}</Badge>
                </button>
              </Card>))}</div>
          )}
          {cmp.data && cmp.data.items.length > 0 && (
            <Card>
              <CardHeader title="Compare your offers" subtitle="What WhatsApp reported for each. It cannot tell us how many sales an offer led to." />
              <div className="overflow-x-auto"><table className="w-full min-w-[560px] text-left text-sm">
                <thead><tr className="text-[13px] text-ink-500">{["Offer", "Sent", "Delivered", "Read", "Not delivered", "Asked to stop", "Likely charge"].map((h) => <th key={h} className="pb-2 pr-3 font-semibold">{h}</th>)}</tr></thead>
                <tbody>{cmp.data.items.map((r) => (
                  <tr key={r.id} className="border-t border-ink-100 text-ink-700">
                    <td className="py-2 pr-3 font-semibold text-ink">{r.name}<span className="block text-[12px] font-normal text-ink-400">{r.started_at ? fmtDate(r.started_at) : ""}</span></td>
                    <td className="pr-3 tabular-nums">{r.sent}</td><td className="pr-3 tabular-nums">{r.delivered} <span className="text-ink-400">({percent(r.delivery_rate)})</span></td>
                    <td className="pr-3 tabular-nums">{r.read} <span className="text-ink-400">({percent(r.read_rate)} of delivered)</span></td><td className="pr-3 tabular-nums">{r.failed}</td><td className="pr-3 tabular-nums">{r.opted_out_after}</td><td className="tabular-nums">{rupees(r.estimated_meta_cost)}</td>
                  </tr>))}</tbody>
              </table></div>
            </Card>
          )}
        </div>
      )}
      {creating && tpl.data && <NewOffer choices={choices} onClose={() => setCreating(false)} onDone={(id) => { setCreating(false); void list.reload(); setOpen(id); }} />}
      {open && <OfferDetail id={open} canEdit={isAdmin} onClose={() => { setOpen(null); void list.reload(); void cmp.reload(); }} onDuplicate={(id) => { void list.reload(); setOpen(id); }} />}
    </>
  );
}

function NewOffer({ choices, onClose, onDone }: { choices: WaTemplates["items"]; onClose: () => void; onDone: (id: string) => void }) {
  const st = useFetch<WaStatus>("/whatsapp/status");
  const locs = useFetch<{ id: string; name: string }[]>("/locations");
  const [f, setF] = useState({ name: "", templateId: choices.find((t) => t.key === "offer")?.id ?? choices[0]?.id ?? "", offer: "", kind: "all", tag: "", days: "30", when: "now", at: "",
    tagsAny: "", tagsAll: "", exclude: "", location: "", notDays: "", never: false });
  const t = choices.find((c) => c.id === f.templateId);
  const isOffer = t?.key === "offer";
  const blanks = isOffer ? 0 : Math.max(t?.variables.length ?? 0, (t?.body?.match(/\{\{\d+\}\}/g) ?? []).length);
  const [map, setMap] = useState<WaMapping[]>([]);
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const advanced = !!st.data && (!st.data.addon_required || st.data.addon?.segmentation === "advanced");
  const m: WaMapping[] = Array.from({ length: blanks }, (_, i) => map[i] ?? { source: i === 0 ? "customer_name" : i === 1 ? "business_name" : "text", value: "" });

  const aud: WaAudience = { kind: f.kind, ...(f.kind === "tag" ? { tag: f.tag.trim() } : {}), ...(f.kind === "new" || f.kind === "existing" ? { days: Number(f.days) } : {}) };
  if (advanced) {
    if (splitList(f.tagsAny).length) aud.tags_any = splitList(f.tagsAny);
    if (splitList(f.tagsAll).length) aud.tags_all = splitList(f.tagsAll);
    if (splitList(f.exclude).length) aud.exclude_tags = splitList(f.exclude);
    if (f.location) aud.location_id = f.location;
    if (f.notDays) aud.not_messaged_days = Number(f.notDays);
    if (f.never) aud.never_messaged = true;
  }
  const variables: WaVariables = isOffer ? { offer_text: f.offer.trim() } : { mapping: m.map((x) => (x.source === "text" ? { source: "text", value: (x.value ?? "").trim() } : { source: x.source })) };
  const messageOk = isOffer ? f.offer.trim().length >= 5 && f.offer.length <= OFFER_MAX : m.every((x) => x.source !== "text" || (x.value ?? "").trim().length > 0);
  const ok = f.name.trim().length >= 2 && !!t && messageOk && (f.kind !== "tag" || f.tag.trim().length > 0) && (f.when === "now" || !!f.at);
  async function save() {
    setBusy(true); setErr(null);
    try {
      const c = await api<WaCampaign>("/whatsapp/campaigns", { method: "POST", body: { name: f.name.trim(), template_id: f.templateId, audience: aud, variables, scheduled_at: f.when === "at" ? fromIstInput(f.at) : null } });
      onDone(c.id);
    } catch (e) { setErr(errorMessage(e)); setBusy(false); }
  }
  return (
    <Modal open onClose={onClose} title="New offer" footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button variant="brand" loading={busy} disabled={!ok} onClick={() => void save()}>Save and review</Button></>}>
      <div className="space-y-4">
        {err && <Alert tone="error">{err}</Alert>}
        <Input label="Name (only you see this)" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Diwali offer" />
        {choices.length > 1 && <Select label="Message" value={f.templateId} onChange={(e) => { setF({ ...f, templateId: e.target.value }); setMap([]); }} hint="Only messages WhatsApp has approved, with plain text, can be used.">{choices.map((c) => <option key={c.id} value={c.id}>{c.key === "offer" ? "FlowQR offer message" : c.name}</option>)}</Select>}
        {t?.body && <p className="rounded-2xl bg-surface-2 p-3 text-[13px] text-ink-700">{t.body}</p>}
        {isOffer
          ? <Textarea label="Your offer" rows={2} maxLength={OFFER_MAX} value={f.offer} onChange={(e) => setF({ ...f, offer: e.target.value })} hint={`${f.offer.length}/${OFFER_MAX}. For example: 10% off all sessions this week.`} />
          : m.map((x, i) => (
            <div key={i} className="grid gap-2 sm:grid-cols-2">
              <Select label={blankLabel(i)} value={x.source} onChange={(e) => setMap(m.map((y, j) => (j === i ? { source: e.target.value as WaMapping["source"], value: y.value } : y)))}>{Object.entries(SOURCE_WORDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select>
              {x.source === "text" && <Input label="Text" maxLength={200} value={x.value ?? ""} onChange={(e) => setMap(m.map((y, j) => (j === i ? { ...y, value: e.target.value } : y)))} />}
            </div>))}
        <Select label="Who should get it?" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value })}>
          <option value="all">Everyone who agreed to receive offers</option><option value="tag">A group of customers</option><option value="new">New customers</option><option value="existing">Earlier customers</option>
        </Select>
        {f.kind === "tag" && <Input label="Group name" value={f.tag} onChange={(e) => setF({ ...f, tag: e.target.value })} hint="The group you gave customers when you added them, for example: regular." />}
        {(f.kind === "new" || f.kind === "existing") && <Input label="Days" type="number" min={1} max={365} value={f.days} onChange={(e) => setF({ ...f, days: e.target.value })} hint={f.kind === "new" ? "Customers added in the last this many days." : "Customers added more than this many days ago."} />}
        {advanced ? (
          <details className="rounded-2xl border border-line p-4"><summary className="cursor-pointer text-sm font-semibold text-ink">More ways to choose (Pro)</summary>
            <div className="mt-3 space-y-3">
              {(locs.data?.length ?? 0) > 0 && <Select label="Only customers at" value={f.location} onChange={(e) => setF({ ...f, location: e.target.value })}><option value="">Any location</option>{locs.data?.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</Select>}
              <Input label="In any of these groups" value={f.tagsAny} onChange={(e) => setF({ ...f, tagsAny: e.target.value })} hint="Separate with commas." />
              <Input label="In all of these groups" value={f.tagsAll} onChange={(e) => setF({ ...f, tagsAll: e.target.value })} hint="Separate with commas." />
              <Input label="Leave out these groups" value={f.exclude} onChange={(e) => setF({ ...f, exclude: e.target.value })} hint="Separate with commas." />
              <Input label="Only customers who have not had an offer in the last (days)" type="number" min={1} max={365} value={f.notDays} onChange={(e) => setF({ ...f, notDays: e.target.value })} />
              <label className="flex items-center gap-2 text-sm text-ink-700"><input type="checkbox" checked={f.never} onChange={(e) => setF({ ...f, never: e.target.checked })} className="h-4 w-4 accent-[#BD3E1B]" />Only customers who have never had an offer</label>
            </div>
          </details>
        ) : <p className="text-[13px] text-ink-500">Choosing by location, several groups or how recently someone got an offer is part of the Pro add-on.</p>}
        <fieldset className="space-y-2 rounded-2xl border border-line p-4"><legend className="px-1 text-sm font-semibold">When?</legend>
          <label className="flex items-center gap-2 text-sm text-ink-700"><input type="radio" name="when" checked={f.when === "now"} onChange={() => setF({ ...f, when: "now" })} className="accent-[#BD3E1B]" />As soon as I approve it</label>
          <label className="flex items-center gap-2 text-sm text-ink-700"><input type="radio" name="when" checked={f.when === "at"} onChange={() => setF({ ...f, when: "at" })} className="accent-[#BD3E1B]" />On a day and time I choose (India time)</label>
          {f.when === "at" && <Input label="Start" type="datetime-local" value={f.at} onChange={(e) => setF({ ...f, at: e.target.value })} />}
        </fieldset>
        <p className="text-[13px] text-ink-500">Only customers who agreed to receive offers, and have not asked to stop, are ever included.</p>
      </div>
    </Modal>
  );
}

function Timeline({ days }: { days: WaCampaignResults["timeline"] }) {
  if (days.length === 0) return null;
  const max = Math.max(...days.map((d) => d.sent), 1);
  return (
    <div className="mt-3"><p className="mb-1 text-[13px] font-semibold text-ink-500">Day by day</p>
      <ul className="space-y-2">{days.map((d) => (
        <li key={d.date} className="text-[13px]">
          <div className="flex items-center justify-between text-ink-700"><span>{fmtDate(d.date)}</span><span className="tabular-nums">{d.sent} sent · {d.delivered} delivered · {d.read} read{d.failed ? ` · ${d.failed} not delivered` : ""}</span></div>
          <div className="mt-1 h-2 rounded-full bg-surface-3" role="img" aria-label={`${d.sent} sent, ${d.delivered} delivered, ${d.read} read`}><div className="h-2 rounded-full bg-ink-300" style={{ width: `${barPercent(d.sent, max)}%` }}><div className="h-2 rounded-full bg-brand-700" style={{ width: `${d.sent ? Math.round((d.delivered * 100) / d.sent) : 0}%` }} /></div></div>
        </li>))}</ul>
    </div>
  );
}

function OfferDetail({ id, canEdit, onClose, onDuplicate }: { id: string; canEdit: boolean; onClose: () => void; onDuplicate: (id: string) => void }) {
  const toast = useToast();
  const pv = useFetch<WaCampaignPreview>(`/whatsapp/campaigns/${id}`);
  const locs = useFetch<{ id: string; name: string }[]>("/locations");
  const started = !!pv.data && ["sending", "paused", "done", "cancelled"].includes(pv.data.status);
  const res = useFetch<WaCampaignResults>(started ? `/whatsapp/campaigns/${id}/results` : null);
  const [seen, setSeen] = useState(false), [busy, setBusy] = useState<string | null>(null), [err, setErr] = useState<string | null>(null), [when, setWhen] = useState("");
  const p = pv.data;
  const blockers = p ? campaignBlockers(p) : [];
  const locName = (lid: string) => locs.data?.find((l) => l.id === lid)?.name;

  async function approve() {
    if (!p) return;
    setBusy("approve"); setErr(null);
    try { await api(`/whatsapp/campaigns/${id}/approve`, { method: "POST", body: { confirm_recipients: p.recipients, accept_estimate: true } }); toast("Approved."); setSeen(false); await pv.reload(); }
    catch (e) { setErr(errorMessage(e)); await pv.reload(); } finally { setBusy(null); }
  }
  async function act(a: "pause" | "resume" | "cancel") {
    setBusy(a); setErr(null);
    try { await api(`/whatsapp/campaigns/${id}/${a}`, { method: "POST" }); await pv.reload(); await res.reload(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(null); }
  }
  async function move() {
    setBusy("move"); setErr(null);
    try { await api(`/whatsapp/campaigns/${id}/reschedule`, { method: "POST", body: { scheduled_at: fromIstInput(when) } }); toast("Start time changed."); setWhen(""); await pv.reload(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(null); }
  }
  async function dup() {
    setBusy("dup"); setErr(null);
    try { const d = await api<WaCampaign>(`/whatsapp/campaigns/${id}/duplicate`, { method: "POST" }); toast("A copy was saved as a draft."); onDuplicate(d.id); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(null); }
  }
  async function download() {
    try { const { blob } = await apiFile(`/whatsapp/campaigns/${id}/results.csv`); const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = "campaign-results.csv"; a.click(); URL.revokeObjectURL(url); } catch (e) { toast(errorMessage(e)); }
  }
  return (
    <Modal open onClose={onClose} title={p?.name ?? "Offer"} footer={<Button variant="secondary" onClick={onClose}>Close</Button>}>
      {!p ? <Skeleton className="h-40" /> : (
        <div className="space-y-4 text-sm">
          {err && <Alert tone="error">{err}</Alert>}
          <div className="flex flex-wrap items-center gap-2"><Badge tone={CAMPAIGN_STATUS[p.status].tone}>{CAMPAIGN_STATUS[p.status].label}</Badge><span className="text-ink-500">{audienceSentence(p.audience, locName)}</span></div>
          {p.message_preview && <div><p className="mb-1 text-[13px] font-semibold text-ink-500">What customers will read</p><p className="rounded-2xl bg-surface-2 p-4 text-ink">{p.message_preview}</p></div>}
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-2xl bg-surface-2 p-4"><p className="text-[13px] text-ink-500">Customers who will get it</p><p className="mt-1 text-2xl font-semibold tabular-nums text-ink">{p.status === "draft" || p.status === "paused" ? p.recipients : p.approved_recipients ?? p.recipients}</p></div>
            <div className="rounded-2xl bg-surface-2 p-4"><p className="text-[13px] text-ink-500">Likely WhatsApp charge</p><p className="mt-1 text-2xl font-semibold tabular-nums text-ink">{rupees(p.status === "draft" ? p.estimate.amount : p.approved_cost ?? p.estimate.amount)}</p></div>
          </div>
          <p className="text-[13px] text-ink-500">{p.estimate.note} {p.excluded_note}</p>
          {["draft", "scheduled", "paused"].includes(p.status) && (
            <div className="rounded-2xl border border-line p-4 text-[13px] text-ink-700">
              <p><b>{p.scheduled_at ? `Starts ${fmtDate(p.scheduled_at)}` : "Starts as soon as it is approved"}.</b> {p.waits_for_hours ? `That is outside sending hours, so it will start at ${new Date(p.starts_at).toLocaleString("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" })}.` : ""} {windowSentence(p.window)}</p>
              {p.recipients > 0 && <p className="mt-1 text-ink-500">Sending to {p.recipients} customers takes about {Math.max(1, p.estimated_minutes)} minute{p.estimated_minutes > 1 ? "s" : ""}.</p>}
              {canEdit && ["draft", "scheduled"].includes(p.status) && !started && (
                <div className="mt-3 flex flex-wrap items-end gap-2"><Input label="Change the start time (India time)" type="datetime-local" value={when || toIstInput(p.scheduled_at)} onChange={(e) => setWhen(e.target.value)} /><Button variant="secondary" loading={busy === "move"} disabled={!when} onClick={() => void move()}>Change time</Button></div>
              )}
            </div>
          )}
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
              <div className="mb-2 flex items-center justify-between"><p className="font-semibold text-ink">Results so far</p>{canEdit && <Button size="sm" variant="secondary" icon={<Download className="h-4 w-4" />} onClick={() => void download()}>Download results</Button>}</div>
              <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {([["Sent", res.data.sent], ["Delivered", `${res.data.delivered} (${percent(res.data.delivery_rate)})`], ["Read", `${res.data.read} (${percent(res.data.read_rate)})`], ["Not delivered", res.data.failed], ["Waiting", res.data.waiting], ["Not sent", res.data.skipped], ["Asked to stop after", res.data.opted_out_after], ["Charge so far", rupees(res.data.estimated_meta_cost)]] as [string, number | string][]).map(([l, v]) => <div key={l} className="rounded-xl bg-surface-2 p-3"><dt className="text-[12px] text-ink-500">{l}</dt><dd className="font-semibold tabular-nums text-ink">{v}</dd></div>)}
              </dl>
              <Timeline days={res.data.timeline} />
              {Object.keys(res.data.skipped_reasons).length > 0 && <ul className="mt-2 list-disc pl-5 text-[13px] text-ink-700">{Object.entries(res.data.skipped_reasons).map(([r, n]) => <li key={r}>{n}: {reasonWords(r)}</li>)}</ul>}
              <p className="mt-2 text-[13px] text-ink-500">“Read” counts only customers who allow read receipts. {res.data.note}</p>
            </div>
          )}
          {canEdit && <div className="border-t border-line pt-3"><Button variant="ghost" size="sm" icon={<Copy className="h-4 w-4" />} loading={busy === "dup"} onClick={() => void dup()}>Make a copy as a draft</Button></div>}
        </div>
      )}
    </Modal>
  );
}
