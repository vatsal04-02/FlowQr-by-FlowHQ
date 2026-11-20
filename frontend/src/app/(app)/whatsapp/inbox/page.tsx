"use client";
import { ArrowLeft, Search } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input, Textarea } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import { CONV_FILTERS, RETENTION_NOTE, senderTag, windowWords, type WaConvList, type WaConvSettings, type WaConvSummary, type WaConvThread } from "@/lib/whatsapp";

const clock = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "");
const BUBBLE = { customer: "bg-surface-2 text-ink", staff: "bg-brand-100 text-ink", ai: "bg-blue-50 text-ink", system: "bg-ink-50 text-ink-700" } as const;

/** Turn the inbox on, and say plainly what is kept and for how long. */
function Setup({ cfg, onChange, isAdmin }: { cfg: WaConvSettings; onChange: () => void; isAdmin: boolean }) {
  const toast = useToast();
  const s = cfg.settings;
  const [f, setF] = useState({ retention: String(s.retention_days), takeover: String(s.takeover_minutes), wait: String(s.debounce_seconds), email: s.notify_email }), [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  async function save(enabled?: boolean) {
    setBusy(true); setErr(null);
    try { await api("/whatsapp/conversations/settings", { method: "PUT", body: { ...(enabled === undefined ? {} : { enabled }), retention_days: Number(f.retention), takeover_minutes: Number(f.takeover), debounce_seconds: Number(f.wait), notify_email: f.email } }); toast("Saved."); onChange(); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <Card>
      <h2 className="text-lg font-semibold text-ink">{cfg.active ? "Inbox settings" : "Turn on the inbox"}</h2>
      <p className="mt-1 text-sm text-ink-700">When a customer writes to your WhatsApp number, you see the conversation here and can reply while their 24-hour window is open. {RETENTION_NOTE(Number(f.retention) || s.retention_days)}</p>
      {!cfg.platform_on && <div className="mt-3"><Alert tone="info" title="Not available yet">FlowQR has not switched conversations on for everyone yet.</Alert></div>}
      {!cfg.addon_ok && <div className="mt-3"><Alert tone="info" title="The WhatsApp add-on is needed">Ask the FlowQR team to switch it on for your business.</Alert></div>}
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <Input label="Keep messages for (days)" type="number" min={30} max={365} value={f.retention} disabled={!isAdmin} onChange={(e) => setF({ ...f, retention: e.target.value })} hint="30 to 365." />
        <Input label="Quiet after a person replies (minutes)" type="number" min={5} max={1440} value={f.takeover} disabled={!isAdmin} onChange={(e) => setF({ ...f, takeover: e.target.value })} hint="How long the assistant stays out of it." />
        <Input label="Wait for more messages (seconds)" type="number" min={2} max={10} value={f.wait} disabled={!isAdmin} onChange={(e) => setF({ ...f, wait: e.target.value })} hint="So a burst is answered once." />
      </div>
      <label className="mt-3 flex items-center gap-2 text-sm text-ink-700"><input type="checkbox" checked={f.email} disabled={!isAdmin} onChange={(e) => setF({ ...f, email: e.target.checked })} className="h-4 w-4 accent-[#BD3E1B]" />Email the owner and admins when a conversation needs a person (the email never contains the message)</label>
      {err && <div className="mt-3"><Alert tone="warning">{err}</Alert></div>}
      {isAdmin ? (
        <div className="mt-4 flex flex-wrap gap-2">
          {!cfg.active ? <Button variant="brand" loading={busy} disabled={!cfg.platform_on || !cfg.addon_ok} onClick={() => void save(true)}>Turn on the inbox</Button> : <><Button variant="secondary" loading={busy} onClick={() => void save()}>Save settings</Button><Button variant="ghost" onClick={() => void save(false)}>Turn off</Button></>}
        </div>
      ) : <p className="mt-3 text-[13px] text-ink-500">Only the owner or an admin can change this.</p>}
    </Card>
  );
}

function Thread({ id, isAdmin, onClose, onChange }: { id: string; isAdmin: boolean; onClose: () => void; onChange: () => void }) {
  const toast = useToast();
  const q = useFetch<WaConvThread>(`/whatsapp/conversations/${id}`);
  const [text, setText] = useState(""), [busy, setBusy] = useState<string | null>(null), [err, setErr] = useState<string | null>(null), [warn, setWarn] = useState<string[] | null>(null);
  const clientId = useRef(crypto.randomUUID());
  const end = useRef<HTMLDivElement>(null);
  const t = q.data;
  useEffect(() => { const h = setInterval(() => void q.reload(), 10000); return () => clearInterval(h); }, [q]);
  useEffect(() => { if (t?.unread) void api(`/whatsapp/conversations/${id}/read`, { method: "POST" }).then(onChange).catch(() => undefined); }, [t?.unread, id, onChange]);
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [t?.messages.length]);
  async function act(path: string, label: string, body?: unknown) {
    setBusy(label); setErr(null);
    try { await api(`/whatsapp/conversations/${id}/${path}`, { method: "POST", body }); await q.reload(); onChange(); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(null); }
  }
  async function send(confirm = false) {
    setBusy("send"); setErr(null);
    try {
      await api(`/whatsapp/conversations/${id}/reply`, { method: "POST", body: { text: text.trim(), confirm_marketing: confirm, client_id: clientId.current } });
      setText(""); setWarn(null); clientId.current = crypto.randomUUID(); await q.reload(); onChange();
    } catch (e) {
      const d = e instanceof ApiError ? (e.detail as { code?: string; terms?: string[] } | null) : null;
      if (d?.code === "marketing_warning") setWarn(d.terms ?? []);
      else setErr(errorMessage(e));
    } finally { setBusy(null); }
  }
  async function remove() {
    if (!window.confirm("Delete this conversation and every message in it? This cannot be undone.")) return;
    try { await api(`/whatsapp/conversations/${id}`, { method: "DELETE" }); toast("Deleted."); onClose(); onChange(); } catch (e) { setErr(errorMessage(e)); }
  }
  if (!t) return <Skeleton className="h-96" />;
  const name = t.contact?.name ?? "A customer";
  return (
    <div className="flex h-[70vh] min-h-[420px] flex-col rounded-2xl bg-surface shadow-sm" data-testid="thread">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-ink-100 p-3">
        <div className="flex min-w-0 items-center gap-2">
          <button type="button" aria-label="Back to the list" onClick={onClose} className="grid h-9 w-9 place-items-center rounded-full hover:bg-ink-50 md:hidden"><ArrowLeft className="h-4 w-4" aria-hidden /></button>
          <div className="min-w-0"><p className="truncate font-semibold text-ink">{name} <span className="font-normal tabular-nums text-ink-500">{t.contact?.phone}</span></p>
            <p className="flex flex-wrap items-center gap-1.5 text-[12px] text-ink-500">{t.contact?.no_consent && <Badge>Contact, no consent</Badge>}{t.contact?.opted_out && <Badge tone="red">Asked to stop</Badge>}{t.status === "needs_human" && <Badge tone="amber">Needs you</Badge>}{t.ai_paused_until && <Badge tone="blue">Assistant paused</Badge>}{t.assigned_name && <span>With {t.assigned_name}</span>}</p></div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {t.ai_paused_until ? <Button size="sm" variant="secondary" loading={busy === "hb"} onClick={() => void act("hand-back", "hb")}>Hand back to assistant</Button> : <Button size="sm" variant="secondary" loading={busy === "to"} onClick={() => void act("take-over", "to")}>Take over</Button>}
          {t.status === "closed" ? <Button size="sm" variant="ghost" onClick={() => void act("reopen", "ro")}>Reopen</Button> : <Button size="sm" variant="ghost" onClick={() => void act("close", "cl")}>Close</Button>}
          {isAdmin && <Button size="sm" variant="ghost" onClick={() => void remove()}>Delete</Button>}
        </div>
      </div>
      {t.handoff_words && t.status === "needs_human" && <div className="border-b border-ink-100 bg-amber-50 px-3 py-2 text-[13px] text-ink-700" data-testid="why">Why you are needed: {t.handoff_words}</div>}
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3" aria-live="polite">
        {t.messages.length === 0 && <p className="text-sm text-ink-500">No messages yet.</p>}
        {t.messages.map((m) => (
          <div key={m.id} className={m.direction === "outbound" ? "flex flex-col items-end" : "flex flex-col items-start"}>
            <p className="mb-0.5 text-[11px] text-ink-500" data-testid="sender">{senderTag(m)} · {clock(m.created_at)}{m.direction === "outbound" && m.status !== "received" ? ` · ${m.status === "failed" ? "not delivered" : m.status}` : ""}</p>
            <div className={`max-w-[85%] whitespace-pre-wrap break-words rounded-2xl px-3 py-2 text-sm ${BUBBLE[m.sender_type]}`}>{m.text ?? <span className="text-ink-500">[{m.msg_type}: FlowQR can only show text]</span>}</div>
            {m.marketing_confirmed && <p className="mt-0.5 text-[11px] text-amber-700">You confirmed this message looks like an offer.</p>}
          </div>))}
        <div ref={end} />
      </div>
      <div className="border-t border-ink-100 p-3">
        <p className="mb-2 text-[12px] text-ink-500" data-testid="window">{windowWords(t.window_open, t.window_closes_at)}</p>
        {err && <div className="mb-2"><Alert tone="warning">{err}</Alert></div>}
        {!t.window_open ? (
          <div className="space-y-2">
            {t.fallback_templates.map((f) => (
              <div key={f.key} className="rounded-xl bg-surface-2 p-3 text-sm">
                <p className="font-semibold text-ink">{f.label}</p>
                {f.text && <p className="mt-1 text-ink-700">{f.text}</p>}
                {f.can_send ? <Button className="mt-2" size="sm" variant="brand" loading={busy === "tpl"} onClick={() => void act("send-template", "tpl", { key: f.key })}>Send this approved message</Button>
                  : <p className="mt-1 text-[13px] text-ink-500">{f.reason === "no_utility_consent" ? "This customer has not agreed to updates about their enquiry, so no message can be sent." : f.reason === "template_not_approved" ? "WhatsApp has not approved this message yet." : "Not available."}</p>}
              </div>))}
          </div>
        ) : (
          <div className="space-y-2">
            {warn && <Alert tone="warning" title="This looks like an offer">A conversation reply cannot be marketing ({warn.join(", ")}). Offers go through Offers, to customers who agreed to them. Send anyway only if this is not an offer.<div className="mt-2 flex gap-2"><Button size="sm" variant="secondary" onClick={() => setWarn(null)}>Change it</Button><Button size="sm" variant="brand" loading={busy === "send"} onClick={() => void send(true)}>It is not an offer, send</Button></div></Alert>}
            <Textarea label="Reply" rows={2} value={text} maxLength={1500} onChange={(e) => { setText(e.target.value); setWarn(null); }} hint="Plain text. Your name is shown to the customer's team members, not to the customer." />
            <Button variant="brand" loading={busy === "send"} disabled={!text.trim()} onClick={() => void send(false)}>Send</Button>
          </div>
        )}
      </div>
    </div>
  );
}

function Inbox() {
  const { isAdmin } = useAuth();
  const params = useSearchParams();
  const cfg = useFetch<WaConvSettings>("/whatsapp/conversations/settings");
  const [filter, setFilter] = useState<"all" | "needs_you" | "unread" | "closed">("all"), [q, setQ] = useState(""), [search, setSearch] = useState(""), [sel, setSel] = useState<string | null>(params.get("c")), [showSettings, setShowSettings] = useState(false);
  useEffect(() => { const h = setTimeout(() => setSearch(q), 300); return () => clearTimeout(h); }, [q]);
  const active = !!cfg.data?.active;
  const list = useFetch<WaConvList>(active ? "/whatsapp/conversations" : null, { filter, q: search || undefined });
  useEffect(() => { if (!active) return; const h = setInterval(() => void list.reload(), 10000); return () => clearInterval(h); }, [active, list]);
  return (
    <>
      <PageHeader title="Inbox" subtitle="Customers who write to your WhatsApp number. You can reply while their 24-hour window is open." actions={cfg.data?.active ? <Button variant="secondary" onClick={() => setShowSettings(!showSettings)}>{showSettings ? "Hide settings" : "Settings"}</Button> : undefined} />
      {cfg.error && <Alert tone="error">{cfg.error}</Alert>}
      {!cfg.data ? <Skeleton className="h-64" /> : (!active || showSettings) ? <Setup cfg={cfg.data} isAdmin={isAdmin} onChange={() => { void cfg.reload(); void list.reload(); }} /> : null}
      {active && (
        <div className="mt-4 grid gap-4 md:grid-cols-[330px_1fr]">
          <div className={sel ? "hidden md:block" : ""}>
            <Card pad={false} className="mb-3 p-3">
              <div className="relative"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden /><input aria-label="Search conversations" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, phone or words" className="min-h-11 w-full rounded-xl border border-ink-200 pl-9 pr-3 text-sm sm:min-h-10" /></div>
              <div className="mt-2 flex flex-wrap gap-1.5" role="tablist" aria-label="Show">{CONV_FILTERS.map((f) => <button key={f.value} type="button" role="tab" aria-selected={filter === f.value} onClick={() => setFilter(f.value)} className={`min-h-9 rounded-full px-3 text-[13px] font-medium ${filter === f.value ? "bg-ink text-white" : "bg-surface-2 text-ink-700"}`}>{f.label}{f.value === "needs_you" && list.data?.needs_you ? ` (${list.data.needs_you})` : f.value === "unread" && list.data?.unread_total ? ` (${list.data.unread_total})` : ""}</button>)}</div>
            </Card>
            {list.error && <Alert tone="error">{list.error}</Alert>}
            {!list.data ? <Skeleton className="h-48" /> : list.data.items.length === 0 ? <EmptyState title={search ? "No conversations match" : "No conversations yet"}>{search ? "Try different words." : "When a customer writes to your WhatsApp number it appears here."}</EmptyState> : (
              <ul className="space-y-2" data-testid="conversation-list">{list.data.items.map((c: WaConvSummary) => (
                <li key={c.id}><button type="button" onClick={() => setSel(c.id)} aria-current={sel === c.id} className={`w-full rounded-2xl p-3 text-left shadow-sm ${sel === c.id ? "bg-brand-50 ring-1 ring-brand-300" : "bg-surface hover:bg-ink-50"}`}>
                  <span className="flex items-center justify-between gap-2"><b className="truncate text-ink">{c.contact?.name ?? c.contact?.phone ?? "A customer"}</b><span className="shrink-0 text-[11px] text-ink-500">{clock(c.last_message_at)}</span></span>
                  <span className="mt-0.5 block truncate text-[13px] text-ink-700">{c.preview_from === "ai" ? "Assistant: " : c.preview_from === "staff" ? "You: " : ""}{c.preview ?? ""}</span>
                  <span className="mt-1 flex flex-wrap items-center gap-1.5">{c.unread > 0 && <Badge tone="blue">{c.unread} new</Badge>}{c.status === "needs_human" && <Badge tone="amber">Needs you</Badge>}{c.contact?.no_consent && <Badge>No consent</Badge>}{!c.window_open && <Badge>Window closed</Badge>}</span>
                </button></li>))}</ul>
            )}
          </div>
          <div className={sel ? "" : "hidden md:block"}>
            {sel ? <Thread key={sel} id={sel} isAdmin={isAdmin} onClose={() => setSel(null)} onChange={() => void list.reload()} /> : <Card><p className="text-sm text-ink-500">Choose a conversation to read it.</p><p className="mt-2 text-[12px] text-ink-500">{cfg.data ? RETENTION_NOTE(cfg.data.settings.retention_days) : ""} Last updated {fmtDate(new Date().toISOString())}.</p></Card>}
          </div>
        </div>
      )}
    </>
  );
}

export default function InboxPage() {
  return <Suspense fallback={<Skeleton className="h-64" />}><Inbox /></Suspense>;
}
