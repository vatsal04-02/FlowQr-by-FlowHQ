"use client";
import { Check, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input, Textarea } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-api";
import { KNOWLEDGE_ORDER, quotaWords, type KnowledgeKind, type WaAiStatus, type WaAiTestReply, type WaKnowledge, type WaKnowledgeItem, type WaUnanswered } from "@/lib/whatsapp";

/** Turn the assistant on: the notice about the AI provider, the switch, and this month's allowance. */
function Switch({ st, onChange, isAdmin }: { st: WaAiStatus; onChange: () => void; isAdmin: boolean }) {
  const toast = useToast();
  const [ack, setAck] = useState(false), [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const on = st.settings.enabled;
  async function save(enabled: boolean) {
    setBusy(true); setErr(null);
    try { await api("/whatsapp/ai/settings", { method: "PUT", body: { enabled, acknowledge_privacy: ack || !!st.settings.privacy_ack_at } }); toast(enabled ? "The assistant is on." : "The assistant is off."); onChange(); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Card>
      <div className="flex flex-wrap items-center gap-2"><h2 className="text-lg font-semibold text-ink">Auto-reply assistant</h2>{on ? <Badge tone="green">On</Badge> : <Badge>Off</Badge>}{!st.available && <Badge tone="amber">Not answering customers yet</Badge>}</div>
      <p className="mt-1 text-sm text-ink-700">The assistant answers customers who write to your WhatsApp number, using only the notes you give it below. It says it is an automated assistant, never talks about offers, and hands the conversation to you when it is unsure. It is a limited beta.</p>
      {st.reason_words && <div className="mt-3" data-testid="why-not"><Alert tone="info" title="Why it is not answering">{st.reason_words}</Alert></div>}
      <p className="mt-3 text-sm text-ink-700" data-testid="quota">{quotaWords(st.quota)}</p>
      {st.quota.limit > 0 && <div className="mt-1 h-2 w-full max-w-sm overflow-hidden rounded-full bg-ink-100" role="progressbar" aria-valuemin={0} aria-valuemax={st.quota.limit} aria-valuenow={st.quota.used} aria-label="Replies used this month"><div className={`h-full ${st.quota.near_limit ? "bg-amber-500" : "bg-brand-500"}`} style={{ width: `${Math.min(100, (st.quota.used / st.quota.limit) * 100)}%` }} /></div>}
      <div className="mt-4 rounded-xl bg-surface-2 p-3 text-[13px] text-ink-700" data-testid="privacy"><p className="font-semibold text-ink">Before you turn it on</p><p className="mt-1">{st.privacy_notice}</p></div>
      {err && <div className="mt-3"><Alert tone="warning">{err}</Alert></div>}
      {isAdmin ? (
        <div className="mt-3 space-y-2">
          {!st.settings.privacy_ack_at && <label className="flex items-start gap-2 text-sm text-ink-700"><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} className="mt-0.5 h-4 w-4 accent-[#BD3E1B]" />I have read this and I understand customer messages are sent to an AI provider.</label>}
          {on ? <Button variant="secondary" loading={busy} onClick={() => void save(false)}>Turn the assistant off</Button> : <Button variant="brand" loading={busy} disabled={!st.settings.privacy_ack_at && !ack} onClick={() => void save(true)}>Turn the assistant on</Button>}
        </div>
      ) : <p className="mt-3 text-[13px] text-ink-500">Only an owner or admin can turn the assistant on or off.</p>}
    </Card>
  );
}

function ItemRow({ it, isAdmin, onChange }: { it: WaKnowledgeItem; isAdmin: boolean; onChange: () => void }) {
  const toast = useToast();
  async function patch(body: unknown) { try { await api(`/whatsapp/ai/knowledge/${it.id}`, { method: "PATCH", body }); onChange(); } catch (e) { toast(errorMessage(e)); } }
  async function remove() { try { await api(`/whatsapp/ai/knowledge/${it.id}`, { method: "DELETE" }); onChange(); } catch (e) { toast(errorMessage(e)); } }
  return (
    <li className="flex items-start gap-3 py-2" data-testid="note">
      <div className="min-w-0 flex-1">
        {it.title && <p className="text-sm font-semibold text-ink">{it.title}{it.price_inr !== null && <span className="ml-2 font-normal tabular-nums text-ink-700">₹{it.price_inr.toLocaleString("en-IN")}</span>}</p>}
        <p className={`whitespace-pre-wrap break-words text-sm ${it.active ? "text-ink-700" : "text-ink-400 line-through"}`}>{it.body}{!it.title && it.price_inr !== null && <span className="ml-2 tabular-nums">₹{it.price_inr.toLocaleString("en-IN")}</span>}</p>
      </div>
      {isAdmin && <div className="flex shrink-0 gap-1"><Button size="sm" variant="ghost" onClick={() => void patch({ active: !it.active })}>{it.active ? "Hide" : "Show"}</Button><Button size="sm" variant="ghost" aria-label="Delete this note" onClick={() => void remove()}><Trash2 size={15} /></Button></div>}
    </li>
  );
}

/** What the assistant may say. Seven sections; offers are not one of them on purpose. */
function Notes({ kb, isAdmin, onChange }: { kb: WaKnowledge; isAdmin: boolean; onChange: () => void }) {
  const toast = useToast();
  const [kind, setKind] = useState<KnowledgeKind>("about"), [title, setTitle] = useState(""), [body, setBody] = useState(""), [price, setPrice] = useState(""), [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const sec = kb.suggestions.sections.find((s) => s.kind === kind);
  const have = (k: KnowledgeKind) => kb.items.filter((i) => i.kind === k);
  async function add() {
    setBusy(true); setErr(null);
    try { await api("/whatsapp/ai/knowledge", { method: "POST", body: { kind, title: title.trim() || null, body: body.trim(), price_inr: kind === "service" && price.trim() ? price.trim() : null } }); setTitle(""); setBody(""); setPrice(""); toast("Added."); onChange(); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  async function importMine() {
    setBusy(true); setErr(null);
    try { const r = await api<{ added: number }>("/whatsapp/ai/knowledge/import", { method: "POST" }); toast(r.added ? `Added ${r.added} notes from your business details.` : "Nothing new to add."); onChange(); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Card>
      <CardHeader title="What the assistant knows" subtitle="It answers only from these notes. If something is not here, it hands the customer to you." />
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {kb.readiness.ready ? <Badge tone="green"><Check size={12} className="mr-1 inline" />Enough to start</Badge> : <Badge tone="amber">Still needed: {kb.readiness.missing.join(", ")}</Badge>}
        {isAdmin && <Button size="sm" variant="secondary" loading={busy} onClick={() => void importMine()}>Fill from my business details</Button>}
      </div>
      <Alert tone="info" title="No offers here">{kb.suggestions.warning}</Alert>
      <div className="mt-3 space-y-4">
        {KNOWLEDGE_ORDER.map((k) => {
          const s = kb.suggestions.sections.find((x) => x.kind === k)!;
          const rows = have(k);
          return (
            <section key={k} aria-label={s.label}>
              <h3 className="text-sm font-semibold text-ink">{s.label}</h3>
              {rows.length === 0 ? <p className="text-[13px] text-ink-500">Nothing yet. Example: {kb.suggestions.examples[k]}</p> : <ul className="divide-y divide-ink-100">{rows.map((it) => <ItemRow key={it.id} it={it} isAdmin={isAdmin} onChange={onChange} />)}</ul>}
            </section>);
        })}
      </div>
      {isAdmin && (
        <div className="mt-5 space-y-3 border-t border-ink-100 pt-4">
          <h3 className="text-sm font-semibold text-ink">Add a note</h3>
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Section">
            {KNOWLEDGE_ORDER.map((k) => { const s = kb.suggestions.sections.find((x) => x.kind === k)!; return <button key={k} type="button" aria-pressed={kind === k} onClick={() => setKind(k)} className={`rounded-full border px-3 py-1 text-[13px] ${kind === k ? "border-brand-500 bg-brand-50 text-ink" : "border-ink-200 text-ink-700"}`}>{s.label}</button>; })}
          </div>
          {(kind === "service" || kind === "faq" || kind === "policy") && <Input label={kind === "service" ? "Service name" : kind === "faq" ? "Short title" : "Policy name"} value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} />}
          <Textarea label={sec?.label ?? "Note"} rows={3} value={body} maxLength={1200} onChange={(e) => setBody(e.target.value)} hint={kb.suggestions.examples[kind]} />
          {kind === "service" && <Input label="Price in rupees (optional)" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value)} hint="Only a price you are happy to be quoted. Do not write offers or discounts." />}
          {sec?.single && have(kind).length > 0 && <p className="text-[13px] text-ink-500">There is already one of these. Hide or delete it above to replace it.</p>}
          {err && <Alert tone="warning">{err}</Alert>}
          <Button variant="brand" loading={busy} disabled={!body.trim() || (!!sec?.single && have(kind).length > 0)} onClick={() => void add()}>Add note</Button>
          <div className="rounded-xl bg-surface-2 p-3 text-[13px] text-ink-700"><p className="font-semibold text-ink">Questions customers of a {kb.suggestions.business_type === "general" ? "business like yours" : kb.suggestions.business_type} often ask</p><ul className="mt-1 list-disc pl-5">{kb.suggestions.questions.map((q) => <li key={q}>{q}</li>)}</ul></div>
        </div>)}
    </Card>
  );
}

/** Try it as a customer. Nothing here is sent to WhatsApp or counted against the month. */
function TestChat({ st, isAdmin }: { st: WaAiStatus; isAdmin: boolean }) {
  const [turns, setTurns] = useState<{ role: "customer" | "assistant"; text: string; note?: string }[]>([]), [text, setText] = useState(""), [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  async function send() {
    const msg = text.trim();
    if (!msg) return;
    setBusy(true); setErr(null);
    try {
      const r = await api<WaAiTestReply>("/whatsapp/ai/test-chat", { method: "POST", body: { message: msg, history: turns.map((t) => ({ role: t.role, text: t.text })) } });
      setTurns([...turns, { role: "customer", text: msg }, { role: "assistant", text: r.reply, note: r.reason_words ?? undefined }]); setText("");
    } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Card>
      <CardHeader title="Test it" subtitle="Type what a customer might write. Nothing here goes to WhatsApp or counts against your replies." />
      {!st.platform.on && <Alert tone="info" title="Not available yet">{st.platform.words}</Alert>}
      <div className="mt-2 max-h-72 space-y-2 overflow-y-auto" aria-live="polite" data-testid="test-thread">
        {turns.map((t, i) => <div key={i} className={`max-w-[90%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm ${t.role === "customer" ? "ml-auto bg-brand-100" : "bg-blue-50"}`}>{t.text}{t.note && <p className="mt-1 text-[12px] text-ink-500">Handed to a person: {t.note}</p>}</div>)}
      </div>
      {err && <div className="mt-2"><Alert tone="warning">{err}</Alert></div>}
      {isAdmin ? (
        <form className="mt-3 flex items-end gap-2" onSubmit={(e) => { e.preventDefault(); void send(); }}>
          <div className="min-w-0 flex-1"><Input label="Customer message" value={text} maxLength={500} onChange={(e) => setText(e.target.value)} /></div>
          <Button variant="brand" type="submit" loading={busy} disabled={!st.platform.on || !text.trim()}>Send</Button>
        </form>) : <p className="mt-2 text-[13px] text-ink-500">Only an owner or admin can test the assistant.</p>}
    </Card>
  );
}

/** What customers asked that the notes could not answer: write the answer once and the assistant has it. */
function Unanswered({ onChange }: { onChange: () => void }) {
  const q = useFetch<{ items: WaUnanswered[] }>("/whatsapp/ai/unanswered");
  const { isAdmin } = useAuth();
  async function done(ids: string[]) { await api("/whatsapp/ai/unanswered/resolve", { method: "POST", body: { ids } }); await q.reload(); onChange(); }
  const items = q.data?.items ?? [];
  return (
    <Card>
      <CardHeader title="Questions it could not answer" subtitle="Add the answer to the notes above, then mark it done." />
      {!q.data ? <Skeleton className="h-16" /> : items.length === 0 ? <EmptyState title="Nothing yet">When a customer asks something your notes do not cover, it shows up here.</EmptyState> : (
        <ul className="divide-y divide-ink-100">{items.map((u) => (
          <li key={u.ids[0]} className="flex items-start justify-between gap-3 py-2"><p className="min-w-0 break-words text-sm text-ink-700">{u.question}{u.count > 1 && <span className="ml-2 text-[12px] text-ink-500">asked {u.count} times</span>}</p>{isAdmin && <Button size="sm" variant="ghost" onClick={() => void done(u.ids)}>Done</Button>}</li>))}</ul>)}
    </Card>
  );
}

export default function AutoReply() {
  const { isAdmin } = useAuth();
  const st = useFetch<WaAiStatus>("/whatsapp/ai/status");
  const kb = useFetch<WaKnowledge>("/whatsapp/ai/knowledge");
  const refresh = () => { void st.reload(); void kb.reload(); };
  return (
    <div className="space-y-5">
      <PageHeader title="Auto-reply" subtitle="An assistant that answers your customers on WhatsApp from your own notes, and hands over to you when it is not sure." />
      {!st.data ? <Skeleton className="h-48" /> : <Switch st={st.data} onChange={refresh} isAdmin={isAdmin} />}
      {!kb.data ? <Skeleton className="h-64" /> : <Notes kb={kb.data} isAdmin={isAdmin} onChange={refresh} />}
      {st.data && <TestChat st={st.data} isAdmin={isAdmin} />}
      <Unanswered onChange={refresh} />
    </div>
  );
}
