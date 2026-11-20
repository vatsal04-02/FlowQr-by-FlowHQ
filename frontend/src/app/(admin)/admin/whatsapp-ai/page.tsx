"use client";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input, Select } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import { tierLabel, type WaAiQuotas } from "@/lib/whatsapp";

/** How many assistant replies each WhatsApp tier includes a month. A number is a dated row that is never edited: a change is a new row with a later date. Start low and set it from the tokens and delay recorded below. */
export default function WhatsAppAi() {
  const toast = useToast();
  const q = useFetch<WaAiQuotas>("/admin/whatsapp/ai-quotas");
  const [f, setF] = useState({ addon_key: "whatsapp_growth", monthly_replies: "", effective_from: "", note: "" });
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  async function add() {
    setBusy(true); setErr(null);
    try { await api("/admin/whatsapp/ai-quotas", { method: "POST", body: { ...f, monthly_replies: Number(f.monthly_replies) } }); toast("Added."); setF({ ...f, monthly_replies: "", note: "" }); await q.reload(); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  const d = q.data;
  return (
    <div className="space-y-5">
      <PageHeader title="WhatsApp assistant" subtitle="Monthly replies by tier, and what the assistant has cost in real use. It stays unavailable to customers until the AI provider's written data terms are confirmed." />
      {!d ? <Skeleton className="h-40" /> : (
        <>
          <Card>
            <CardHeader title="Is it available?" />
            <p className="flex flex-wrap items-center gap-2 text-sm text-ink-700" data-testid="platform">{d.platform.on ? <Badge tone="green">Available</Badge> : <Badge tone="amber">Unavailable</Badge>}Provider: {d.platform.provider}. Terms confirmed in writing: {d.platform.terms_verified ? `yes, for ${d.platform.terms_provider}` : "no"}. Reason: {d.platform.reason ?? "none"}.</p>
            <p className="mt-2 text-[13px] text-ink-500">These are server settings (WHATSAPP_AI_ENABLED, WHATSAPP_AI_TERMS_VERIFIED, WHATSAPP_AI_TERMS_PROVIDER, WHATSAPP_AI_KILL_SWITCH). This page only shows them.</p>
          </Card>
          <Card>
            <CardHeader title="Replies included each month" subtitle={d.note} />
            <ul className="divide-y divide-ink-100">{d.items.map((r) => <li key={r.id} className="flex flex-wrap items-baseline gap-x-3 py-2 text-sm"><b className="text-ink">{tierLabel(r.addon_key)}</b><span className="tabular-nums">{r.monthly_replies} replies</span><span className="text-[13px] text-ink-500">from {fmtDate(r.effective_from)} · {r.note}</span></li>)}</ul>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <Select label="Tier" value={f.addon_key} onChange={(e) => setF({ ...f, addon_key: e.target.value })}><option value="whatsapp_starter">Starter</option><option value="whatsapp_growth">Growth</option><option value="whatsapp_pro">Pro</option></Select>
              <Input label="Replies a month" inputMode="numeric" value={f.monthly_replies} onChange={(e) => setF({ ...f, monthly_replies: e.target.value })} />
              <Input label="From (date)" type="date" value={f.effective_from} onChange={(e) => setF({ ...f, effective_from: e.target.value })} />
              <Input label="Why" value={f.note} maxLength={300} onChange={(e) => setF({ ...f, note: e.target.value })} hint="For example: raised after a month of real use." />
            </div>
            {err && <div className="mt-2"><Alert tone="warning">{err}</Alert></div>}
            <Button className="mt-3" variant="brand" loading={busy} disabled={!f.monthly_replies || !f.effective_from || f.note.trim().length < 5} onClick={() => void add()}>Add a dated value</Button>
          </Card>
          <Card>
            <CardHeader title="This month in real use" subtitle="Tokens and delay per model, from the assistant's own records. Use these to price the allowance." />
            {d.this_month.length === 0 ? <p className="text-sm text-ink-500">No assistant runs yet.</p> : <ul className="divide-y divide-ink-100">{d.this_month.map((r) => <li key={`${r.provider}${r.model_version}`} className="py-2 text-sm text-ink-700"><b className="text-ink">{r.provider} / {r.model_version}</b> · {r.runs} runs · {r.prompt_tokens.toLocaleString("en-IN")} tokens in, {r.completion_tokens.toLocaleString("en-IN")} out · average {r.avg_latency_ms} ms</li>)}</ul>}
          </Card>
        </>)}
    </div>
  );
}
