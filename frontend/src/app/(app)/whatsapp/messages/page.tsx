"use client";
import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import { MESSAGE_STATUS, rupees, TEMPLATE_STATUS, TEMPLATE_TITLES, type WaMessageRow, type WaTemplates, type WaUsage } from "@/lib/whatsapp";

/** Your messages, what was sent and what it probably cost. Costs are always estimates and WhatsApp's charge is separate from FlowQR's fee. */
export default function Messages() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const tpl = useFetch<WaTemplates>("/whatsapp/templates");
  const [month, setMonth] = useState("");
  const usage = useFetch<WaUsage>("/whatsapp/usage", { month });
  const [status, setStatus] = useState("");
  const act = useFetch<{ total: number; items: WaMessageRow[] }>("/whatsapp/messages", { status, limit: 25 });
  const [busy, setBusy] = useState<string | null>(null);

  async function sync() {
    setBusy("sync");
    try { await api("/whatsapp/templates/sync", { method: "POST" }); await tpl.reload(); toast("Checked with WhatsApp."); } catch (e) { toast(errorMessage(e)); } finally { setBusy(null); }
  }
  async function prepare(key: string) {
    setBusy(key);
    try { await api("/whatsapp/templates/install", { method: "POST", body: { key } }); await tpl.reload(); toast("Sent to WhatsApp for approval."); } catch (e) { toast(errorMessage(e)); } finally { setBusy(null); }
  }
  const u = usage.data;
  return (
    <>
      <PageHeader title="Messages and costs" subtitle="The messages WhatsApp has approved for you, what was sent, and what it probably cost." />
      <div className="space-y-4">
        <Card>
          <CardHeader title="Your messages" subtitle="WhatsApp has to approve every message before it can be sent. We send them for you." action={isAdmin ? <Button variant="secondary" size="sm" loading={busy === "sync"} icon={<RefreshCw className="h-4 w-4" />} onClick={() => void sync()}>Check with WhatsApp</Button> : undefined} />
          {tpl.error && <Alert tone="error">{tpl.error}</Alert>}
          {!tpl.data ? <Skeleton className="h-24" /> : (
            <ul className="divide-y divide-ink-100">{tpl.data.available.map((a) => {
              const t = tpl.data?.items.find((x) => x.key === a.key);
              const s = t ? TEMPLATE_STATUS[t.status] : null;
              return (
                <li key={a.key} className="flex flex-wrap items-start justify-between gap-3 py-3">
                  <div className="min-w-0 max-w-xl"><p className="font-semibold text-ink">{TEMPLATE_TITLES[a.key] ?? a.key}</p><p className="mt-0.5 text-[13px] text-ink-500">{a.body.replace(/\{\{\d+\}\}/g, "…")}</p>{t?.rejection_reason && <p className="mt-1 text-[13px] text-neg">Reason: {t.rejection_reason}</p>}</div>
                  <div className="flex items-center gap-2">{s ? <Badge tone={s.tone}>{s.label}</Badge> : isAdmin ? <Button size="sm" variant="secondary" loading={busy === a.key} onClick={() => void prepare(a.key)}>Prepare</Button> : <Badge tone="gray">Not prepared</Badge>}{t && t.category !== a.category && <Badge tone="amber">WhatsApp treats this as {t.category === "marketing" ? "an offer" : "a service message"}</Badge>}</div>
                </li>);
            })}</ul>
          )}
        </Card>

        <Card>
          <CardHeader title="This month" subtitle="WhatsApp's charge is an estimate, separate from FlowQR's fee." action={<input type="month" aria-label="Month" value={month || u?.month || ""} onChange={(e) => setMonth(e.target.value)} className="min-h-10 rounded-xl border border-ink-200 px-3 text-sm" />} />
          {usage.error && <Alert tone="error">{usage.error}</Alert>}
          {!u ? <Skeleton className="h-24" /> : (
            <div className="space-y-3">
              {u.price_warning && <Alert tone="warning" title="Prices not checked yet">{u.price_warning}</Alert>}
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                {([["Tried to send", u.totals.attempted], ["Sent", u.totals.sent], ["Delivered", u.totals.delivered], ["Read", u.totals.read], ["Not delivered", u.totals.failed]] as [string, number][]).map(([l, v]) => <div key={l} className="rounded-2xl bg-surface-2 p-4"><p className="text-[13px] text-ink-500">{l}</p><p className="mt-1 text-2xl font-semibold tabular-nums text-ink">{v}</p></div>)}
              </div>
              <div className="rounded-2xl bg-surface-2 p-4"><p className="text-[13px] text-ink-500">Likely WhatsApp charge so far</p><p className="mt-1 text-2xl font-semibold tabular-nums text-ink">{rupees(u.estimated_meta_cost)}</p>{u.delivery_rate !== null && <p className="mt-1 text-[13px] text-ink-500">{u.delivery_rate}% of sent messages were delivered.</p>}</div>
              <p className="text-[13px] text-ink-500">{u.note} “Read” counts only customers who allow read receipts. Delivered is not the same as read.</p>
              <p className="text-[13px] text-ink-500">Rough price per delivered message: offers {rupees(u.rates.marketing.rate)}, other messages {rupees(u.rates.utility.rate)}. {u.rates.marketing.verified ? "" : "These prices have not been checked against WhatsApp's own price list yet."}</p>
            </div>
          )}
        </Card>

        <Card>
          <CardHeader title="Recent messages" action={<select aria-label="Show" value={status} onChange={(e) => setStatus(e.target.value)} className="min-h-10 rounded-xl border border-ink-200 px-3 text-sm"><option value="">All</option><option value="delivered">Delivered</option><option value="read">Read</option><option value="failed">Not delivered</option></select>} />
          {!act.data ? <Skeleton className="h-24" /> : act.data.items.length === 0 ? <EmptyState title="Nothing sent yet">Messages appear here once your helpers or offers start sending.</EmptyState> : (
            <ul className="divide-y divide-ink-100 text-sm">{act.data.items.map((m) => (
              <li key={m.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                <span className="text-ink-700">{m.to ?? "A customer"}{m.phone_last4 ? <span className="text-ink-400"> · …{m.phone_last4}</span> : null} <span className="text-ink-400">{m.category === "marketing" ? "Offer" : "Update"}</span></span>
                <span className="flex items-center gap-2"><Badge tone={MESSAGE_STATUS[m.status]?.tone ?? "gray"}>{MESSAGE_STATUS[m.status]?.label ?? m.status}</Badge><span className="text-[13px] text-ink-400">{fmtDate(m.sent_at ?? m.created_at)}</span></span>
              </li>))}</ul>
          )}
        </Card>
      </div>
    </>
  );
}
