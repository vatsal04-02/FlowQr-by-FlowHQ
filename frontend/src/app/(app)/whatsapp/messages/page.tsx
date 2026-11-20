"use client";
import clsx from "clsx";
import { AlertTriangle, ChevronDown, Download, MousePointerClick, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { useToast } from "@/components/ui/Toast";
import { Bubble, Chips, Figure, IconButton, Meter, Note } from "@/components/whatsapp/ui";
import { api, apiFile, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import { LINK_CLICKED, linkClickWords, MESSAGE_STATUS, rupees, TEMPLATE_STATUS, TEMPLATE_TITLES, type WaMessageRow, type WaTemplates, type WaUsage } from "@/lib/whatsapp";
import { funnel } from "@/lib/whatsapp-ui";

const FUNNEL_TONE = { sent: "brand", delivered: "brand", read: "pos" } as const;

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

  async function exportMessages() {
    try {
      const { blob } = await apiFile("/whatsapp/messages/export");
      const url = URL.createObjectURL(blob); const a = document.createElement("a"); a.href = url; a.download = "whatsapp-messages.csv"; a.click(); URL.revokeObjectURL(url);
    } catch (e) { toast(errorMessage(e)); }
  }
  async function sync() {
    setBusy("sync");
    try { await api("/whatsapp/templates/sync", { method: "POST" }); await tpl.reload(); toast("Checked with WhatsApp."); } catch (e) { toast(errorMessage(e)); } finally { setBusy(null); }
  }
  async function prepare(key: string) {
    setBusy(key);
    try { await api("/whatsapp/templates/install", { method: "POST", body: { key } }); await tpl.reload(); toast("Sent to WhatsApp for approval."); } catch (e) { toast(errorMessage(e)); } finally { setBusy(null); }
  }
  const u = usage.data;
  const bars = u ? funnel(u.totals) : [];
  const maxClicks = u?.links ? Math.max(1, ...u.links.by_day.map((x) => x.clicks)) : 1;
  return (
    <>
      <PageHeader title="Messages" actions={isAdmin ? <IconButton label="Download messages" icon={Download} onClick={() => void exportMessages()} /> : undefined} />
      <div className="space-y-3 sm:space-y-4">
        <section className="panel p-5 sm:p-6" aria-label="This month">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[13px] text-muted">Likely WhatsApp charge</p>
              {!u ? <Skeleton className="mt-1 h-9 w-32" /> : <Figure value={rupees(u.estimated_meta_cost)} />}
              {u && u.delivery_rate !== null && <p className="mt-1 text-[13px] text-muted">{u.delivery_rate}% delivered</p>}
            </div>
            <input type="month" aria-label="Month" value={month || u?.month || ""} onChange={(e) => setMonth(e.target.value)} className="min-h-11 rounded-2xl border border-ink-200 bg-white px-3 text-[14px]" />
          </div>
          {usage.error && <div className="mt-3"><Alert tone="error">{usage.error}</Alert></div>}
          {u && (
            <>
              {u.price_warning && <div className="mt-4"><Alert tone="warning" title="Prices not checked yet">{u.price_warning}</Alert></div>}
              <ul className="mt-5 space-y-3.5" aria-label="Messages this month">
                {bars.map((b) => (
                  <li key={b.key} className="grid grid-cols-[76px_1fr_auto] items-center gap-3">
                    <span className="text-[14px] text-ink-700">{b.label}</span>
                    <Meter value={b.share} tone={FUNNEL_TONE[b.key]} label={`${b.label}: ${b.value}`} />
                    <span className="num min-w-6 text-right text-[17px] font-semibold text-ink">{b.value}</span>
                  </li>
                ))}
              </ul>
              {u.totals.failed > 0 && <p className="mt-4 inline-flex items-center gap-1.5 rounded-full bg-neg-tint px-3 py-1.5 text-[13px] font-medium text-neg"><AlertTriangle className="h-3.5 w-3.5" aria-hidden />{u.totals.failed} not delivered</p>}
              <details className="group mt-4 border-t border-line pt-1">
                <summary className="flex min-h-11 cursor-pointer list-none items-center justify-between text-[14px] font-semibold text-ink-700 [&::-webkit-details-marker]:hidden">About these numbers<ChevronDown aria-hidden className="h-4 w-4 text-ink-400 transition-transform group-open:rotate-180" /></summary>
                <div className="space-y-2 pb-1 text-[13px] leading-5 text-muted">
                  <p>WhatsApp&apos;s charge is an estimate, separate from FlowQR&apos;s fee.</p>
                  <p>{u.totals.attempted} tried to send. {u.note} “Read” counts only customers who allow read receipts. Delivered is not the same as read.</p>
                  <p>Rough price per delivered message: offers {rupees(u.rates.marketing.rate)}, other messages {rupees(u.rates.utility.rate)}. {u.rates.marketing.verified ? "" : "These prices have not been checked against WhatsApp's own price list yet."}</p>
                </div>
              </details>
            </>
          )}
        </section>

        {u?.links?.enabled && (
          <section className="panel p-5 sm:p-6" data-testid="link-clicks" aria-label={LINK_CLICKED}>
            <div className="flex items-center gap-4">
              <span aria-hidden className="grid h-11 w-11 shrink-0 place-items-center rounded-2xl bg-brand-50 text-brand-700"><MousePointerClick className="h-[22px] w-[22px]" strokeWidth={1.75} /></span>
              <div className="min-w-0 flex-1"><p className="text-[13px] text-muted">{LINK_CLICKED}</p><Figure value={u.links.link_clicked} /></div>
            </div>
            <p className="mt-2 text-[13px] text-muted">{u.links.messages_with_a_click} message{u.links.messages_with_a_click === 1 ? "" : "s"} had its link opened this month.</p>
            {u.links.by_day.length > 0 && (
              <ul className="mt-3 space-y-2" aria-label="Link clicks by day">{u.links.by_day.map((d) => (
                <li key={d.date} className="grid grid-cols-[84px_1fr_auto] items-center gap-3 text-[13px]"><span className="text-muted">{fmtDate(d.date)}</span><Meter value={Math.round((d.clicks / maxClicks) * 100)} tone="brand" label={`${fmtDate(d.date)}: ${d.clicks}`} /><span className="num text-ink-700">{d.clicks}</span></li>
              ))}</ul>
            )}
            <Note className="mt-3">{u.links.note}</Note>
          </section>
        )}

        <section className="panel p-5 sm:p-6" aria-label="Your messages">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-[17px] font-semibold text-ink">Your messages</h2>
            {isAdmin && <Button variant="secondary" size="sm" loading={busy === "sync"} icon={<RefreshCw className="h-4 w-4" />} onClick={() => void sync()}>Check</Button>}
          </div>
          <p className="mt-0.5 text-[13px] text-muted">WhatsApp approves each one first.</p>
          {tpl.error && <div className="mt-3"><Alert tone="error">{tpl.error}</Alert></div>}
          {!tpl.data ? <Skeleton className="mt-3 h-24" /> : (
            <ul className="mt-3 divide-y divide-line">{tpl.data.available.map((a) => {
              const t = tpl.data?.items.find((x) => x.key === a.key);
              const s = t ? TEMPLATE_STATUS[t.status] : null;
              return (
                <li key={a.key} className="py-4 first:pt-1">
                  <div className="flex items-center justify-between gap-3">
                    <p className="min-w-0 text-[15px] font-semibold text-ink">{TEMPLATE_TITLES[a.key] ?? a.key}</p>
                    {s ? <Badge tone={s.tone}>{s.label}</Badge> : isAdmin ? <Button size="sm" variant="secondary" loading={busy === a.key} onClick={() => void prepare(a.key)}>Prepare</Button> : <Badge tone="gray">Not prepared</Badge>}
                  </div>
                  <div className="mt-2 flex flex-col rounded-2xl bg-surface-2 p-3"><Bubble side="out" className={clsx("max-w-full", s?.tone === "red" && "opacity-70")}>{a.body.replace(/\{\{\d+\}\}/g, "…")}</Bubble></div>
                  {t && t.category !== a.category && <p className="mt-2"><Badge tone="amber">WhatsApp treats this as {t.category === "marketing" ? "an offer" : "a service message"}</Badge></p>}
                  {t?.rejection_reason && <p className="mt-2 text-[13px] text-neg">Reason: {t.rejection_reason}</p>}
                </li>);
            })}</ul>
          )}
        </section>

        <section className="panel p-5 sm:p-6" aria-label="Recent messages">
          <h2 className="text-[17px] font-semibold text-ink">Recent</h2>
          <div className="mt-3"><Chips label="Show" value={status} onChange={setStatus} options={[{ value: "", label: "All" }, { value: "delivered", label: "Delivered" }, { value: "read", label: "Read" }, { value: "failed", label: "Not delivered" }]} /></div>
          {!act.data ? <Skeleton className="mt-3 h-24" /> : act.data.items.length === 0 ? <div className="mt-3"><EmptyState title="Nothing sent yet">Messages show here once helpers or offers start sending.</EmptyState></div> : (
            <ul className="mt-2 divide-y divide-line text-sm">{act.data.items.map((m) => (
              <li key={m.id} className="flex items-center justify-between gap-3 py-3">
                <div className="min-w-0"><p className="truncate text-[15px] text-ink">{m.to ?? "A customer"}{m.phone_last4 ? <span className="text-ink-400"> · …{m.phone_last4}</span> : null}</p><p className="text-[13px] text-muted">{m.category === "marketing" ? "Offer" : "Update"} · {fmtDate(m.sent_at ?? m.created_at)}</p></div>
                <span className="flex shrink-0 flex-col items-end gap-1"><Badge tone={MESSAGE_STATUS[m.status]?.tone ?? "gray"}>{MESSAGE_STATUS[m.status]?.label ?? m.status}</Badge>{m.link_clicked_at && <Badge tone="blue">{linkClickWords(m.link_clicked_at)}</Badge>}</span>
              </li>))}</ul>
          )}
        </section>
      </div>
    </>
  );
}
