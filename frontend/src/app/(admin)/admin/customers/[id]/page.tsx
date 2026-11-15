"use client";
import { ArrowLeft, Ban, LifeBuoy, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input, Select, Textarea } from "@/components/ui/Form";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { rupees } from "@/lib/billing";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import { SUB_TONE, type TenantRow } from "@/lib/admin-ui";

interface Detail {
  tenant: TenantRow & { support_note: string | null; email: string | null; phone: string | null };
  subscription: { plan: string; status: string; source: string; max_locations: number; monthly_ai_generations: number; max_staff: number; trial_ends_at: string | null; current_period_end: string | null; cancel_at_period_end: boolean; razorpay_subscription_id: string | null } | null;
  members: { user_id: string; email: string; full_name: string; role: string; is_active: boolean; email_verified: boolean }[];
  locations: { id: string; name: string; city: string | null; is_active: boolean; has_review_link: boolean }[];
  cards: { id: string; card_code: string; status: string }[];
  payments: { id: string; kind: string; status: string; amount_paise: number; created_at: string }[];
  audit: { action: string; created_at: string; meta: Record<string, unknown> }[];
  ai_generations_this_month: number;
}

export default function CustomerDetail() {
  const { id } = useParams<{ id: string }>();
  const toast = useToast();
  const { data: d, error, reload } = useFetch<Detail>(`/admin/tenants/${id}`);
  const [modal, setModal] = useState<"suspend" | "sub" | "support" | null>(null);
  const [text, setText] = useState(""); const [plan, setPlan] = useState(""); const [status, setStatus] = useState(""); const [extend, setExtend] = useState(""); const [sup, setSup] = useState("open");
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<unknown>, msg: string) {
    setBusy(true);
    try { await fn(); toast(msg); setModal(null); setText(""); await reload(); } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); }
  }
  if (error) return <Alert tone="error">{error}</Alert>;
  if (!d) return <Skeleton className="h-96" />;
  const t = d.tenant, s = d.subscription;
  return (
    <>
      <Link href="/admin/customers" className="mb-4 inline-flex min-h-11 items-center gap-1.5 text-sm font-semibold text-brand-700 hover:underline"><ArrowLeft className="h-4 w-4" aria-hidden />All customers</Link>
      <PageHeader eyebrow="Customer" title={t.name} subtitle={`${t.category ?? ""} · owner ${t.owner_email ?? "?"} · joined ${fmtDate(t.created_at)}`} actions={<>
        <Button variant="secondary" icon={<LifeBuoy className="h-4 w-4" />} onClick={() => { setSup(t.support_status === "none" ? "open" : t.support_status); setText(t.support_note ?? ""); setModal("support"); }}>Support status</Button>
        {t.is_active ? <Button variant="danger" icon={<Ban className="h-4 w-4" />} onClick={() => setModal("suspend")}>Suspend</Button> : <Button icon={<ShieldCheck className="h-4 w-4" />} loading={busy} onClick={() => void run(() => api(`/admin/tenants/${id}/unsuspend`, { method: "POST" }), "Account restored.")}>Unsuspend</Button>}
      </>} />
      {!t.is_active && <div className="mb-4"><Alert tone="error" title="Suspended">{t.suspension_reason}</Alert></div>}
      {t.support_status !== "none" && <div className="mb-4"><Alert tone="warning" title={`Support: ${t.support_status}`}>{d.tenant.support_note}</Alert></div>}

      <div className="grid gap-5 lg:grid-cols-2">
        <Card><CardHeader title="Subscription" action={<Button size="sm" variant="secondary" onClick={() => { setPlan(""); setStatus(""); setExtend(""); setText(""); setModal("sub"); }}>Manage</Button>} />
          {s ? <dl className="grid grid-cols-2 gap-3 text-sm">
            {[["Plan", s.plan], ["Status", <Badge key="s" tone={SUB_TONE[s.status] ?? "gray"}>{s.status}</Badge>], ["Source", s.source], ["Limits", `${s.max_locations} loc · ${s.monthly_ai_generations} AI · ${s.max_staff} staff`],
              ["Trial ends", fmtDate(s.trial_ends_at)], ["Period end", fmtDate(s.current_period_end)], ["Razorpay", s.razorpay_subscription_id ?? "–"], ["AI this month", d.ai_generations_this_month]].map(([k, v]) => <div key={k as string}><dt className="text-ink-500">{k}</dt><dd className="mt-0.5 break-all font-semibold">{v}</dd></div>)}
          </dl> : <p className="text-sm text-ink-500">No subscription.</p>}
        </Card>
        <Card><CardHeader title="Team" /><ul className="divide-y divide-ink-100 text-sm">{d.members.map((m) => (
          <li key={m.user_id} className="flex flex-wrap items-center justify-between gap-2 py-2.5"><div><p className="font-semibold">{m.full_name} <Badge tone={m.role === "owner" ? "blue" : "gray"}>{m.role}</Badge></p><p className="text-ink-500">{m.email}{!m.email_verified && " · unverified"}</p></div>
            <Button size="sm" variant={m.is_active ? "danger" : "secondary"} onClick={() => { if (confirm(`${m.is_active ? "Deactivate" : "Reactivate"} ${m.email}?`)) void run(() => api(`/admin/users/${m.user_id}`, { method: "PATCH", body: { is_active: !m.is_active } }), "User updated."); }}>{m.is_active ? "Deactivate" : "Reactivate"}</Button></li>))}</ul></Card>
        <Card><CardHeader title={`Locations (${d.locations.length})`} /><ul className="space-y-1.5 text-sm">{d.locations.map((l) => <li key={l.id} className="flex items-center justify-between"><span>{l.name}{l.city && <span className="text-ink-500"> · {l.city}</span>}</span><Badge tone={l.has_review_link ? "green" : "amber"}>{l.has_review_link ? "link set" : "no link"}</Badge></li>)}</ul></Card>
        <Card><CardHeader title={`Cards (${d.cards.length})`} /><div className="flex flex-wrap gap-2">{d.cards.map((c) => <Badge key={c.id} tone={c.status === "active" ? "green" : "gray"}>{c.card_code} · {c.status}</Badge>)}{d.cards.length === 0 && <p className="text-sm text-ink-500">None assigned.</p>}</div></Card>
        <Card><CardHeader title="Recent payments" /><ul className="divide-y divide-ink-100 text-sm">{d.payments.map((p) => <li key={p.id} className="flex justify-between py-2"><span>{fmtDate(p.created_at)} · {p.kind === "card_order" ? "Cards" : "Subscription"}</span><span className="font-semibold tabular-nums">{rupees(p.amount_paise)} <Badge tone={p.status === "captured" ? "green" : p.status === "failed" ? "red" : "gray"}>{p.status}</Badge></span></li>)}{d.payments.length === 0 && <li className="py-2 text-ink-500">No payments.</li>}</ul></Card>
        <Card><CardHeader title="Recent activity" /><ul className="space-y-1.5 text-xs">{d.audit.map((a, i) => <li key={i} className="flex justify-between gap-3"><code className="text-ink-700">{a.action}</code><span className="text-ink-500">{fmtDate(a.created_at, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}</span></li>)}</ul></Card>
      </div>

      <Modal open={modal === "suspend"} onClose={() => setModal(null)} title="Suspend this business?" footer={<><Button variant="secondary" onClick={() => setModal(null)}>Cancel</Button><Button variant="danger" loading={busy} disabled={text.trim().length < 3} onClick={() => void run(() => api(`/admin/tenants/${id}/suspend`, { method: "POST", body: { reason: text.trim() } }), "Account suspended.")}>Suspend</Button></>}>
        <p className="mb-3 text-sm text-ink-700">Users lose access and the business&rsquo;s QR/NFC cards show an &ldquo;inactive&rdquo; notice. Data is kept. This is recorded in the audit log.</p>
        <Input label="Reason (shown to the customer)" value={text} onChange={(e) => setText(e.target.value)} />
      </Modal>
      <Modal open={modal === "support"} onClose={() => setModal(null)} title="Support status" footer={<><Button variant="secondary" onClick={() => setModal(null)}>Cancel</Button><Button loading={busy} onClick={() => void run(() => api(`/admin/tenants/${id}/support`, { method: "PATCH", body: { status: sup, note: text || null } }), "Support status saved.")}>Save</Button></>}>
        <div className="space-y-4"><Select label="Status" value={sup} onChange={(e) => setSup(e.target.value)}><option value="none">No open issue</option><option value="open">Open</option><option value="waiting">Waiting on customer</option><option value="resolved">Resolved</option></Select><Textarea label="Internal note" value={text} onChange={(e) => setText(e.target.value)} /></div>
      </Modal>
      <Modal open={modal === "sub"} onClose={() => setModal(null)} title="Manual subscription override" footer={<><Button variant="secondary" onClick={() => setModal(null)}>Cancel</Button><Button loading={busy} disabled={text.trim().length < 3} onClick={() => void run(() => api(`/admin/tenants/${id}/subscription`, { method: "POST", body: { plan: plan || null, status: status || null, extend_trial_days: extend ? Number(extend) : null, note: text.trim() } }), "Subscription updated.")}>Apply</Button></>}>
        <div className="space-y-4">
          <Alert tone="warning">This changes FlowQR access only. It does <b>not</b> change or cancel a live Razorpay subscription.</Alert>
          <Select label="Plan" value={plan} onChange={(e) => setPlan(e.target.value)}><option value="">Keep current</option><option value="starter">Starter</option><option value="growth">Growth</option><option value="pro">Pro</option></Select>
          <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Keep current</option><option value="manual">Manual / complimentary</option><option value="active">Active</option><option value="trialing">Trialing</option><option value="expired">Expired</option><option value="canceled">Canceled</option></Select>
          <Input label="Extend trial by (days)" inputMode="numeric" value={extend} onChange={(e) => setExtend(e.target.value)} />
          <Input label="Reason (required, goes to audit log)" value={text} onChange={(e) => setText(e.target.value)} />
        </div>
      </Modal>
    </>
  );
}
