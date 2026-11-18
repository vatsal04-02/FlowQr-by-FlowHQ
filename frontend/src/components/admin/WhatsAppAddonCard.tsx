"use client";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader } from "@/components/ui/Card";
import { Input, Select } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useFetch } from "@/lib/use-api";
import { connectionWords, type WaConnection, type WaStatus, type WaTier } from "@/lib/whatsapp";

interface Summary { enabled: boolean; addon: (WaTier & { since: string }) | null; tiers: WaTier[]; connection: WaConnection | null; counts: WaStatus["counts"] }

/** Platform administrators: record a business's WhatsApp tier by hand (no billing is connected, nothing is charged from here) and see where its connection stands. */
export function WhatsAppAddonCard({ tenantId }: { tenantId: string }) {
  const toast = useToast();
  const q = useFetch<Summary>(`/admin/tenants/${tenantId}/whatsapp`);
  const [tier, setTier] = useState(""), [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null);
  const s = q.data;
  const current = s?.addon?.key ?? "";
  async function save() {
    setBusy(true); setErr(null);
    try { await api(`/admin/tenants/${tenantId}/whatsapp-addon`, { method: "PUT", body: { addon_key: tier || null, reason: reason.trim() } }); toast("WhatsApp add-on recorded."); setReason(""); await q.reload(); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  const words = connectionWords(s?.connection ?? null);
  return (
    <Card>
      <CardHeader title="WhatsApp add-on" action={s ? <Badge tone={s.addon ? "green" : "gray"}>{s.addon ? s.addon.label : "Not on"}</Badge> : undefined} />
      {q.error && <Alert tone="error">{q.error}</Alert>}
      {s && (
        <div className="space-y-3 text-sm">
          {!s.enabled && <p className="text-ink-500">WhatsApp automation is switched off on this server. You can still record a tier ahead of launch.</p>}
          <p className="text-ink-700">Connection: <Badge tone={words.tone}>{words.label}</Badge>{s.connection?.display_phone_number ? <span className="ml-2 tabular-nums">{s.connection.display_phone_number}</span> : null} · {s.counts.contacts} customers, {s.counts.marketing} agreed to offers.</p>
          <Select label="Tier" value={tier || current} onChange={(e) => setTier(e.target.value)} hint="Recorded by hand. Nothing is billed from here, and WhatsApp's own message charges are separate.">
            <option value="">None</option>
            {s.tiers.map((t) => <option key={t.key} value={t.key}>{t.label}: {t.automation_limit} automations, reference ₹{t.price_inr_month}/month</option>)}
          </Select>
          <Input label="Reason (required, kept in the audit log)" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Paid ₹499 by UPI on 12 Nov" />
          {err && <Alert tone="error">{err}</Alert>}
          <Button loading={busy} disabled={reason.trim().length < 5 || (tier || current) === current} onClick={() => void save()}>Record</Button>
        </div>
      )}
    </Card>
  );
}
