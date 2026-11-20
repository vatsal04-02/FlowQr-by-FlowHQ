"use client";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Input } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";
import { deliveryWords, keyStatusWords, webhookUrlProblem, type WaApiKey, type WaDelivery, type WaIntegrations, type WaWebhookEndpoint } from "@/lib/whatsapp";

const clock = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "numeric", minute: "2-digit" }) : "never");

/** Shown once, with a copy button. After the owner leaves this box the value cannot be seen again. */
function Once({ label, value, note }: { label: string; value: string; note?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="mt-3 rounded-xl border border-amber-300 bg-amber-50 p-3" data-testid="once">
      <p className="text-sm font-semibold text-ink">{label}</p>
      <p className="mt-0.5 text-[13px] text-ink-700">{note ?? "Copy it now. It will not be shown again."}</p>
      <code className="mt-2 block break-all rounded-lg bg-white px-3 py-2 text-[13px] text-ink" data-testid="once-value">{value}</code>
      <Button className="mt-2" size="sm" variant="secondary" onClick={() => { void navigator.clipboard?.writeText(value).then(() => setCopied(true)).catch(() => undefined); }}>{copied ? "Copied" : "Copy"}</Button>
    </div>
  );
}

function Keys({ d, onChange }: { d: WaIntegrations; onChange: () => void }) {
  const toast = useToast();
  const [name, setName] = useState(""), [scopes, setScopes] = useState<string[]>([]), [rate, setRate] = useState("60"), [busy, setBusy] = useState(false), [err, setErr] = useState<string | null>(null), [made, setMade] = useState<WaApiKey | null>(null);
  async function create() {
    setBusy(true); setErr(null);
    try { const k = await api<WaApiKey>("/whatsapp/integrations/keys", { method: "POST", body: { name, scopes, rate_limit_per_min: Number(rate) } }); setMade(k); setName(""); setScopes([]); onChange(); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
  }
  async function revoke(k: WaApiKey) {
    try { await api(`/whatsapp/integrations/keys/${k.id}/revoke`, { method: "POST" }); toast("Revoked. It stops working now."); onChange(); } catch (e) { toast(errorMessage(e)); }
  }
  return (
    <Card>
      <CardHeader title="API keys" subtitle="A key lets one of your own systems (a shop, a booking tool) add customers, record visits and enquiries and create bookings. Each key does only what you tick." />
      {d.keys.length === 0 ? <p className="text-sm text-ink-500">No keys yet.</p> : (
        <ul className="divide-y divide-ink-100">{d.keys.map((k) => (
          <li key={k.id} className="py-2.5" data-testid="key">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1"><b className="text-sm text-ink">{k.name}</b><code className="text-[12px] text-ink-500">{k.prefix}…</code><Badge tone={k.active ? "green" : "gray"}>{keyStatusWords(k)}</Badge></div>
            <p className="text-[13px] text-ink-500">{k.scopes.map((s) => d.scopes[s] ?? s).join(", ")} · up to {k.rate_limit_per_min} requests a minute · last used {clock(k.last_used_at)}</p>
            {k.active && <Button className="mt-1" size="sm" variant="ghost" onClick={() => void revoke(k)}>Revoke</Button>}
          </li>))}</ul>)}
      {made?.key && <Once label={`Your new key: ${made.name}`} value={made.key} note={made.note} />}
      <div className="mt-4 space-y-3 border-t border-ink-100 pt-4">
        <h3 className="text-sm font-semibold text-ink">Make a key</h3>
        <Input label="Name" value={name} maxLength={80} onChange={(e) => setName(e.target.value)} hint="The system that will use it, for example Shop checkout." />
        <fieldset><legend className="text-sm font-medium text-ink">What it may do</legend>
          {Object.entries(d.scopes).map(([s, w]) => <label key={s} className="mt-1 flex items-center gap-2 text-sm text-ink-700"><input type="checkbox" checked={scopes.includes(s)} onChange={(e) => setScopes(e.target.checked ? [...scopes, s] : scopes.filter((x) => x !== s))} className="h-4 w-4 accent-[#BD3E1B]" />{w}</label>)}
        </fieldset>
        <Input label="Requests a minute (10 to 600)" type="number" min={10} max={600} value={rate} onChange={(e) => setRate(e.target.value)} />
        {err && <Alert tone="warning">{err}</Alert>}
        <Button variant="brand" loading={busy} disabled={name.trim().length < 2 || scopes.length === 0} onClick={() => void create()}>Make the key</Button>
        <p className="text-[12px] text-ink-500">Adding a customer through a key records no consent by itself. To record that a customer agreed, the request must say so and say how.</p>
      </div>
    </Card>
  );
}

function Endpoints({ d, onChange }: { d: WaIntegrations; onChange: () => void }) {
  const toast = useToast();
  const [url, setUrl] = useState(""), [events, setEvents] = useState<string[]>([]), [busy, setBusy] = useState<string | null>(null), [err, setErr] = useState<string | null>(null), [made, setMade] = useState<WaWebhookEndpoint | null>(null);
  const problem = url ? webhookUrlProblem(url) : null;
  async function create() {
    setBusy("create"); setErr(null);
    try { const e = await api<WaWebhookEndpoint>("/whatsapp/integrations/endpoints", { method: "POST", body: { url: url.trim(), events } }); setMade(e); setUrl(""); setEvents([]); onChange(); }
    catch (e) { setErr(errorMessage(e)); } finally { setBusy(null); }
  }
  async function act(id: string, label: string, path: string, method: string, body?: unknown, ok = "Done.") {
    setBusy(id + label);
    try { const r = await api<WaWebhookEndpoint & { status?: string }>(`/whatsapp/integrations/endpoints/${id}${path}`, { method, body }); if (r?.secret) setMade(r); toast(label === "test" ? `Test ${r.status ?? "sent"}.` : ok); onChange(); } catch (e) { toast(errorMessage(e)); } finally { setBusy(null); }
  }
  return (
    <Card>
      <CardHeader title="Webhooks" subtitle="FlowQR can tell your system when something happens. Each message is signed so you can check it came from us. No message text is ever included." />
      {d.endpoints.length === 0 ? <p className="text-sm text-ink-500">No endpoints yet.</p> : (
        <ul className="divide-y divide-ink-100">{d.endpoints.map((e) => (
          <li key={e.id} className="py-2.5" data-testid="endpoint">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1"><b className="break-all text-sm text-ink">{e.url}</b>{e.active ? <Badge tone="green">On</Badge> : <Badge tone="amber">Off</Badge>}<span className="text-[12px] text-ink-500">secret ends …{e.secret_hint}</span></div>
            <p className="text-[13px] text-ink-500">{e.events.map((x) => d.events[x] ?? x).join(" · ")}</p>
            {e.disabled_reason && <p className="text-[13px] text-amber-700">{e.disabled_reason}</p>}
            <p className="text-[12px] text-ink-500">Last success: {clock(e.last_success_at)}{e.failure_streak > 0 ? ` · ${e.failure_streak} failed in a row` : ""}</p>
            <div className="mt-1 flex flex-wrap gap-1.5">
              <Button size="sm" variant="secondary" loading={busy === e.id + "test"} onClick={() => void act(e.id, "test", "/test", "POST")}>Send a test</Button>
              <Button size="sm" variant="ghost" onClick={() => void act(e.id, "toggle", "", "PATCH", { active: !e.active }, e.active ? "Turned off." : "Turned on.")}>{e.active ? "Turn off" : "Turn on"}</Button>
              <Button size="sm" variant="ghost" onClick={() => void act(e.id, "rotate", "", "PATCH", { rotate_secret: true }, "New secret made.")}>New secret</Button>
              <Button size="sm" variant="ghost" onClick={() => void act(e.id, "delete", "", "DELETE", undefined, "Removed.")}>Remove</Button>
            </div>
          </li>))}</ul>)}
      {made?.secret && <Once label="Signing secret" value={made.secret} note={made.note} />}
      <div className="mt-4 space-y-3 border-t border-ink-100 pt-4">
        <h3 className="text-sm font-semibold text-ink">Add an endpoint</h3>
        <Input label="Address (https only)" value={url} onChange={(e) => setUrl(e.target.value)} error={problem ?? undefined} hint="It must be reachable from the internet. Private and internal addresses are refused." />
        <fieldset><legend className="text-sm font-medium text-ink">Send me</legend>
          {Object.entries(d.events).map(([ev, w]) => <label key={ev} className="mt-1 flex items-center gap-2 text-sm text-ink-700"><input type="checkbox" checked={events.includes(ev)} onChange={(e) => setEvents(e.target.checked ? [...events, ev] : events.filter((x) => x !== ev))} className="h-4 w-4 accent-[#BD3E1B]" />{w}</label>)}
        </fieldset>
        {err && <Alert tone="warning">{err}</Alert>}
        <Button variant="brand" loading={busy === "create"} disabled={!!webhookUrlProblem(url) || events.length === 0} onClick={() => void create()}>Add the endpoint</Button>
      </div>
    </Card>
  );
}

function Deliveries({ onChange }: { onChange: () => void }) {
  const toast = useToast();
  const q = useFetch<{ items: WaDelivery[] }>("/whatsapp/integrations/deliveries");
  async function retry(id: string) { try { await api(`/whatsapp/integrations/deliveries/${id}/retry`, { method: "POST" }); toast("It will be sent again shortly."); await q.reload(); onChange(); } catch (e) { toast(errorMessage(e)); } }
  const items = q.data?.items ?? [];
  return (
    <Card>
      <CardHeader title="Recent deliveries" subtitle="What was sent to your endpoints, and whether it arrived." />
      {!q.data ? <Skeleton className="h-16" /> : items.length === 0 ? <EmptyState title="Nothing sent yet">Events show up here once something happens and an endpoint is listening.</EmptyState> : (
        <ul className="divide-y divide-ink-100">{items.map((x) => (
          <li key={x.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm" data-testid="delivery"><span className="text-ink-700"><b className="text-ink">{x.event_type}</b> · {clock(x.created_at)} · {deliveryWords(x)}</span>{x.status === "dead" && <Button size="sm" variant="ghost" onClick={() => void retry(x.id)}>Try again</Button>}</li>))}</ul>)}
    </Card>
  );
}

export default function Integrations() {
  const q = useFetch<WaIntegrations>("/whatsapp/integrations");
  const d = q.data;
  return (
    <div className="space-y-5">
      <PageHeader title="Integrations" subtitle="Connect your own systems to FlowQR with API keys and signed webhooks. Part of the WhatsApp Pro add-on." />
      {!d ? (q.error ? <Alert tone="info" title="Not available">Integrations are for owners and admins, and are not switched on for everyone yet.</Alert> : <Skeleton className="h-48" />) : (
        <>
          {!d.platform_on && <Alert tone="info" title="Not available yet">Integrations have not been switched on for everyone yet.</Alert>}
          {d.platform_on && !d.plan_ok && <Alert tone="info" title="Part of the Pro add-on">Ask the FlowQR team to move your WhatsApp add-on to Pro. Existing keys stay and work again if you do.</Alert>}
          {d.platform_on && d.plan_ok && (
            <>
              <Keys d={d} onChange={() => void q.reload()} />
              <Endpoints d={d} onChange={() => void q.reload()} />
              <Deliveries onChange={() => void q.reload()} />
              <Card><CardHeader title="Calling the API" /><p className="text-sm text-ink-700">Send your key as <code>Authorization: Bearer &lt;key&gt;</code> and, on every POST, an <code>Idempotency-Key</code> header so a retry never does the work twice. The addresses are under <code>{d.base_path}</code>: <code>/me</code>, <code>/customers</code>, <code>/visits</code>, <code>/enquiries</code>, <code>/bookings</code>. Version {d.api_version}.</p></Card>
            </>)}
        </>)}
    </div>
  );
}
