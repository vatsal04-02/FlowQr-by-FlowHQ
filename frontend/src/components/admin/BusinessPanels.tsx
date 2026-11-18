"use client";
import { Copy, Mail, MessageCircle, Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader } from "@/components/ui/Card";
import { Input, Select, Textarea } from "@/components/ui/Form";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { fmtDate } from "@/lib/format";

export interface BusinessInfo { id: string; name: string; category: string | null; contact_name: string | null; phone: string | null; email: string | null; address: string | null; website: string | null; origin?: string; created_by?: string | null; updated_by?: string | null; updated_at?: string | null; is_active: boolean; managed_access?: string }
export interface LocationInfo { id: string; name: string; city: string | null; address_line?: string | null; phone?: string | null; review_url?: string | null; is_active: boolean; has_review_link: boolean }
export interface AgreementInfo { id: string; recorded_at: string; recorded_by: string | null; terms_version: string; method: string; note: string | null; statement: string }
export interface ClaimInfo { enabled: boolean; has_owner: boolean; invitations: { id: string; email: string; expires_at: string; state: string; allowlist: { ok: boolean; reason: string | null; message: string } }[] }
export interface UsageInfo { month_started: string; review_writings: { used: number; limit: number }; replies: { used: number; limit: number }; generations_logged: number; cost_usd: number; active: boolean }

const METHODS: [string, string][] = [["in_person", "In person, at the shop"], ["phone", "By phone"], ["whatsapp", "On WhatsApp"], ["paper", "On paper"], ["other", "Another way"]];
const methodLabel = (m: string) => METHODS.find(([v]) => v === m)?.[1] ?? m;
const blank = (v: string) => (v.trim() === "" ? null : v.trim());

/** Runs a save, shows the result as a toast and refreshes the page data. */
function useSaver(reload: () => Promise<unknown> | void) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  async function run(fn: () => Promise<unknown>, ok: string): Promise<boolean> {
    setBusy(true); setErr(null);
    try { await fn(); toast(ok); await reload(); return true; } catch (e) { setErr(errorMessage(e)); return false; } finally { setBusy(false); }
  }
  return { busy, err, run, setErr };
}

export function BusinessDetailsCard({ b, reload }: { b: BusinessInfo; reload: () => Promise<unknown> | void }) {
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ name: "", category: "", contact_name: "", phone: "", email: "", address: "", website: "" });
  const { busy, err, run, setErr } = useSaver(reload);
  const start = () => { setF({ name: b.name, category: b.category ?? "", contact_name: b.contact_name ?? "", phone: b.phone ?? "", email: b.email ?? "", address: b.address ?? "", website: b.website ?? "" }); setErr(null); setOpen(true); };
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <Card><CardHeader title="Business details" action={<Button size="sm" variant="secondary" icon={<Pencil className="h-3.5 w-3.5" />} onClick={start}>Edit</Button>} />
      <dl className="grid grid-cols-2 gap-3 text-sm">
        {[["Category", b.category], ["Contact person", b.contact_name], ["Phone", b.phone], ["Email", b.email], ["Website", b.website], ["Address", b.address], ["Created by", b.created_by], ["Last changed by", b.updated_by ? `${b.updated_by} · ${fmtDate(b.updated_at ?? null)}` : null]]
          .map(([k, v]) => <div key={k as string}><dt className="text-ink-500">{k}</dt><dd className="mt-0.5 break-words font-semibold">{(v as string) || <span className="font-normal text-ink-400">–</span>}</dd></div>)}
      </dl>
      <Modal open={open} onClose={() => setOpen(false)} title="Edit business details" footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
        <Button loading={busy} disabled={f.name.trim().length < 2} onClick={() => void run(() => api(`/admin/tenants/${b.id}`, { method: "PATCH", body: { name: f.name.trim(), category: blank(f.category), contact_name: blank(f.contact_name), phone: blank(f.phone), email: blank(f.email), address: blank(f.address), website: blank(f.website) } }), "Details saved.").then((ok) => ok && setOpen(false))}>Save</Button></>}>
        <div className="space-y-4">{err && <Alert tone="error">{err}</Alert>}
          <Input label="Business name" value={f.name} onChange={set("name")} />
          <div className="grid gap-4 sm:grid-cols-2"><Input label="Category" value={f.category} onChange={set("category")} /><Input label="Contact person" value={f.contact_name} onChange={set("contact_name")} /></div>
          <div className="grid gap-4 sm:grid-cols-2"><Input label="Phone" inputMode="tel" value={f.phone} onChange={set("phone")} /><Input label="Email" type="email" value={f.email} onChange={set("email")} /></div>
          <Input label="Website" value={f.website} onChange={set("website")} placeholder="https://" /><Input label="Address" value={f.address} onChange={set("address")} />
        </div>
      </Modal>
    </Card>
  );
}

export function LocationsCard({ tenantId, locations, reload }: { tenantId: string; locations: LocationInfo[]; reload: () => Promise<unknown> | void }) {
  const [edit, setEdit] = useState<LocationInfo | "new" | null>(null);
  const [f, setF] = useState({ name: "", city: "", address_line: "", phone: "", review_url: "" });
  const { busy, err, run, setErr } = useSaver(reload);
  const open = (l: LocationInfo | "new") => { setErr(null); setF(l === "new" ? { name: "", city: "", address_line: "", phone: "", review_url: "" } : { name: l.name, city: l.city ?? "", address_line: l.address_line ?? "", phone: l.phone ?? "", review_url: l.review_url ?? "" }); setEdit(l); };
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  async function save() {
    if (!edit) return;
    const body = { name: f.name.trim(), city: blank(f.city), address_line: blank(f.address_line), phone: blank(f.phone), review_url: blank(f.review_url) };
    const ok = edit === "new" ? await run(() => api(`/admin/tenants/${tenantId}/locations`, { method: "POST", body }), "Location added.") : await run(() => api(`/admin/tenants/${tenantId}/locations/${edit.id}`, { method: "PATCH", body }), "Location saved.");
    if (ok) setEdit(null);
  }
  async function toggle(l: LocationInfo) {
    const next = !l.is_active;
    try { await api(`/admin/tenants/${tenantId}/locations/${l.id}`, { method: "PATCH", body: { is_active: next } }); }
    catch (e) {
      if (e instanceof ApiError && e.code === "confirmation_required") {
        if (!confirm(`${e.message}\n\nTurn this location off anyway?`)) return;
        await run(() => api(`/admin/tenants/${tenantId}/locations/${l.id}`, { method: "PATCH", body: { is_active: false, confirm: true } }), "Location turned off.");
        return;
      }
      setErr(errorMessage(e)); return;
    }
    await run(async () => undefined, next ? "Location turned on." : "Location turned off.");
  }
  return (
    <Card><CardHeader title={`Locations (${locations.length})`} action={<Button size="sm" variant="secondary" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => open("new")}>Add location</Button>} />
      {err && !edit && <div className="mb-3"><Alert tone="error">{err}</Alert></div>}
      <ul className="divide-y divide-ink-100 text-sm">{locations.map((l) => (
        <li key={l.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
          <div className="min-w-0"><p className="font-semibold">{l.name}{!l.is_active && <Badge tone="gray">off</Badge>}</p><p className="text-ink-500">{[l.address_line, l.city].filter(Boolean).join(", ") || "No address"}</p></div>
          <div className="flex items-center gap-2"><Badge tone={l.has_review_link ? "green" : "amber"}>{l.has_review_link ? "review link set" : "no review link"}</Badge>
            <Button size="sm" variant="secondary" onClick={() => open(l)}>Edit</Button><Button size="sm" variant="secondary" onClick={() => void toggle(l)}>{l.is_active ? "Turn off" : "Turn on"}</Button></div></li>))}
        {locations.length === 0 && <li className="py-2 text-ink-500">No locations.</li>}</ul>
      <Modal open={edit !== null} onClose={() => setEdit(null)} title={edit === "new" ? "Add a location" : "Edit location"} footer={<><Button variant="secondary" onClick={() => setEdit(null)}>Cancel</Button><Button loading={busy} disabled={f.name.trim().length < 2} onClick={() => void save()}>Save</Button></>}>
        <div className="space-y-4">{err && <Alert tone="error">{err}</Alert>}
          <Input label="Location name" value={f.name} onChange={set("name")} /><div className="grid gap-4 sm:grid-cols-2"><Input label="City" value={f.city} onChange={set("city")} /><Input label="Phone" inputMode="tel" value={f.phone} onChange={set("phone")} /></div>
          <Input label="Address" value={f.address_line} onChange={set("address_line")} />
          <Input label="Google review link" value={f.review_url} onChange={set("review_url")} placeholder="https://g.page/r/…/review" hint="Changing this changes where every card at this location sends customers." />
        </div>
      </Modal>
    </Card>
  );
}

/** The offline agreement record. It is the administrator's statement, never the shopkeeper's own acceptance, and never an age confirmation. */
export function AgreementCard({ tenantId, agreements, reload }: { tenantId: string; agreements: AgreementInfo[]; reload: () => Promise<unknown> | void }) {
  const [open, setOpen] = useState(false);
  const [method, setMethod] = useState("in_person"), [note, setNote] = useState(""), [sure, setSure] = useState(false);
  const { busy, err, run, setErr } = useSaver(reload);
  return (
    <Card><CardHeader title="Offline agreement" action={<Button size="sm" variant="secondary" onClick={() => { setMethod("in_person"); setNote(""); setSure(false); setErr(null); setOpen(true); }}>Record agreement</Button>} />
      {agreements.length === 0 ? <p className="text-sm text-ink-500">Nothing recorded. If you took this business through the FlowQR terms in person, by phone or on WhatsApp, record it here.</p> : (
        <ul className="space-y-3 text-sm">{agreements.map((a) => (
          <li key={a.id} className="rounded-xl bg-surface-2 p-3"><p className="font-semibold">{methodLabel(a.method)} · {fmtDate(a.recorded_at, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })}</p>
            <p className="text-ink-500">Recorded by {a.recorded_by ?? "an administrator"} · terms {a.terms_version}</p>{a.note && <p className="mt-1">{a.note}</p>}
            <p className="mt-1 text-xs text-ink-500">{a.statement}</p></li>))}</ul>)}
      <Modal open={open} onClose={() => setOpen(false)} title="Record an offline agreement" footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button><Button loading={busy} disabled={!sure} onClick={() => void run(() => api(`/admin/tenants/${tenantId}/agreement`, { method: "POST", body: { method, note: blank(note), confirm: true } }), "Agreement recorded.").then((ok) => ok && setOpen(false))}>Save record</Button></>}>
        <div className="space-y-4">{err && <Alert tone="error">{err}</Alert>}
          <Alert tone="warning">This is <b>your</b> statement, saved with your name and the time. It does not mean the shopkeeper accepted the terms themselves, and it says nothing about their age.</Alert>
          <Select label="How were they taken through the terms?" value={method} onChange={(e) => setMethod(e.target.value)}>{METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select>
          <Input label="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
          <label className="flex min-h-11 items-start gap-2.5 text-sm"><input type="checkbox" checked={sure} onChange={(e) => setSure(e.target.checked)} className="mt-1 h-5 w-5" /><span>I took this business through the FlowQR terms and am recording that on their behalf.</span></label>
        </div>
      </Modal>
    </Card>
  );
}

export function ManagedAccessCard({ tenantId, state, usage, reload }: { tenantId: string; state: string; usage: UsageInfo; reload: () => Promise<unknown> | void }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const { busy, err, run, setErr } = useSaver(reload);
  const revoked = state === "revoked";
  const meter = (label: string, u: { used: number; limit: number }) => (
    <div key={label}><div className="flex justify-between text-sm"><span className="text-ink-500">{label}</span><span className="font-semibold tabular-nums">{u.used} of {u.limit}</span></div>
      <div className="mt-1 h-2 overflow-hidden rounded-full bg-ink-100" role="progressbar" aria-label={label} aria-valuenow={u.used} aria-valuemin={0} aria-valuemax={u.limit}><div className={`h-full ${u.used >= u.limit ? "bg-red-500" : "bg-brand-600"}`} style={{ width: `${Math.min(100, u.limit ? (u.used / u.limit) * 100 : 0)}%` }} /></div></div>);
  return (
    <Card><CardHeader title="Managed access and AI use" action={state === "managed" || revoked ? <Button size="sm" variant={revoked ? "secondary" : "danger"} onClick={() => { setNote(""); setErr(null); setOpen(true); }}>{revoked ? "Restore" : "Revoke"}</Button> : undefined} />
      {state === "managed" && <p className="mb-3 text-sm text-ink-700"><Badge tone="green">Launch plan, managed by FlowQR</Badge> No trial, no billing and no automatic subscription. Limited to 200 AI review writings and 200 AI replies a month.</p>}
      {revoked && <div className="mb-3"><Alert tone="warning">AI features are off for this business. Its cards, scans and review page still work.</Alert></div>}
      {state !== "managed" && !revoked && <p className="mb-3 text-sm text-ink-500">This business has its own subscription. Manage it from the Subscription card.</p>}
      <div className="space-y-3">{meter("AI review writings this month", usage.review_writings)}{meter("AI replies this month", usage.replies)}</div>
      <p className="mt-3 text-sm text-ink-500">{usage.generations_logged} AI calls this month · cost ${usage.cost_usd.toFixed(4)}</p>
      <Modal open={open} onClose={() => setOpen(false)} title={revoked ? "Restore Launch access?" : "Revoke Launch access?"} footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button><Button variant={revoked ? "primary" : "danger"} loading={busy} disabled={note.trim().length < 3} onClick={() => void run(() => api(`/admin/tenants/${tenantId}/managed-access`, { method: "POST", body: { action: revoked ? "restore" : "revoke", note: note.trim() } }), revoked ? "Access restored." : "Access revoked.").then((ok) => ok && setOpen(false))}>{revoked ? "Restore" : "Revoke"}</Button></>}>
        <div className="space-y-4">{err && <Alert tone="error">{err}</Alert>}<p className="text-sm text-ink-700">{revoked ? "AI review writing and replies come back." : "AI review writing and replies stop. Cards, scans and the plain review page keep working."} This is recorded in the audit log.</p>
          <Textarea label="Reason (required)" rows={2} value={note} onChange={(e) => setNote(e.target.value)} /></div>
      </Modal>
    </Card>
  );
}

interface ClaimOut { email: string; delivery: string; email_sent: boolean | null; link: string | null; whatsapp_url: string | null; expires_at: string }

/** Optional: invite the shopkeeper to take ownership. Switched off on the server unless CLAIM_INVITATIONS_ENABLED is set. Nothing about cards depends on this. */
export function ClaimCard({ tenantId, claim, reload }: { tenantId: string; claim: ClaimInfo; reload: () => Promise<unknown> | void }) {
  const toast = useToast();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState(""), [delivery, setDelivery] = useState<"link" | "email">("link");
  const [out, setOut] = useState<ClaimOut | null>(null);
  const [revoking, setRevoking] = useState<ClaimInfo["invitations"][number] | null>(null);
  const [alsoRemove, setAlsoRemove] = useState(false);
  const { busy, err, run, setErr } = useSaver(reload);
  const copy = async (text: string) => { try { await navigator.clipboard.writeText(text); toast("Copied."); } catch { toast("Could not copy. Select the link and copy it.", "error"); } };
  return (
    <Card><CardHeader title="Owner login (optional)" action={claim.enabled && !claim.has_owner ? <Button size="sm" variant="secondary" onClick={() => { setEmail(""); setOut(null); setErr(null); setOpen(true); }}>Invite owner</Button> : undefined} />
      {claim.has_owner ? <p className="text-sm text-ink-700">This business has an owner login. Invitations to claim it are closed.</p> : !claim.enabled ? (
        <p className="text-sm text-ink-500">Claim invitations are switched off. The business works fully without a login: its cards, scans and review page do not need one.</p>
      ) : <p className="mb-2 text-sm text-ink-500">The shopkeeper does not need to claim this. If they want their own login, invite them by email or send them a link on WhatsApp. Links expire and can be revoked.</p>}
      {claim.invitations.length > 0 && <ul className="mt-2 divide-y divide-ink-100 text-sm">{claim.invitations.map((i) => (
        <li key={i.id} className="flex flex-wrap items-center justify-between gap-2 py-2"><span className="min-w-0 break-all">{i.email}<span className="block text-xs text-ink-500">expires {fmtDate(i.expires_at)}</span></span>
          <span className="flex items-center gap-2"><Badge tone={i.state === "open" ? "blue" : i.state === "accepted" ? "green" : "gray"}>{i.state}</Badge>
            {i.state === "open" && <Button size="sm" variant="secondary" onClick={() => { setAlsoRemove(false); setErr(null); setRevoking(i); }}>Revoke</Button>}
            {(i.state === "revoked" || i.state === "expired") && i.allowlist.ok && <Button size="sm" variant="secondary" onClick={() => { if (confirm(`Remove ${i.email} from the sign-up list? They will no longer be able to create an account.`)) void run(() => api(`/admin/tenants/${tenantId}/claim/${i.id}/revoke`, { method: "POST", body: { remove_from_allowlist: true } }), "Removed from the sign-up list."); }}>Remove from sign-up list</Button>}</span></li>))}</ul>}
      <Modal open={revoking !== null} onClose={() => setRevoking(null)} title="Revoke this invitation?" footer={<><Button variant="secondary" onClick={() => setRevoking(null)}>Back</Button>
        <Button variant="danger" loading={busy} onClick={() => revoking && void run(async () => {
          const r = await api<{ allowlist: { removed: boolean; message: string | null } }>(`/admin/tenants/${tenantId}/claim/${revoking.id}/revoke`, { method: "POST", body: { remove_from_allowlist: alsoRemove } });
          if (alsoRemove) toast(r.allowlist.removed ? "Invitation revoked and the email removed from the sign-up list." : `Invitation revoked. ${r.allowlist.message ?? ""}`);
        }, "Invitation revoked.").then((ok) => ok && setRevoking(null))}>Revoke</Button></>}>
        {revoking && <div className="space-y-4">{err && <Alert tone="error">{err}</Alert>}
          <p className="text-sm text-ink-700">The link for <b>{revoking.email}</b> stops working straight away. The invitation and its history stay in the audit log.</p>
          <label className={`flex min-h-11 items-start gap-2.5 text-sm ${revoking.allowlist.ok ? "" : "opacity-60"}`}><input type="checkbox" disabled={!revoking.allowlist.ok} checked={alsoRemove && revoking.allowlist.ok} onChange={(e) => setAlsoRemove(e.target.checked)} className="mt-1 h-5 w-5" />
            <span>Also remove this email from the sign-up list<span className="block text-xs text-ink-500">{revoking.allowlist.message}</span></span></label>
        </div>}
      </Modal>
      <Modal open={open} onClose={() => setOpen(false)} title="Invite the shopkeeper to take over" footer={out ? <Button onClick={() => setOpen(false)}>Done</Button> : <><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button>
        <Button loading={busy} disabled={!email.includes("@")} onClick={() => void run(async () => { setOut(await api<ClaimOut>(`/admin/tenants/${tenantId}/claim`, { method: "POST", body: { email: email.trim(), delivery } })); }, "Invitation created.")}>Create invitation</Button></>}>
        {out ? (
          <div className="space-y-3 text-sm">
            {out.delivery === "email" ? (out.email_sent ? <Alert tone="success">Email sent to {out.email}.</Alert> : <Alert tone="warning">The email could not be sent. Revoke this invitation and use a link instead.</Alert>) : (
              <><Alert tone="warning">This link is shown once and cannot be shown again. It expires {fmtDate(out.expires_at)}.</Alert>
                <input readOnly aria-label="Invitation link" value={out.link ?? ""} onFocus={(e) => e.currentTarget.select()} className="min-h-11 w-full rounded-xl border border-ink-200 px-3 text-xs" />
                <div className="flex flex-wrap gap-2"><Button variant="secondary" icon={<Copy className="h-4 w-4" />} onClick={() => void copy(out.link ?? "")}>Copy link</Button>
                  {out.whatsapp_url && <a href={out.whatsapp_url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center gap-2 rounded-full bg-surface-2 px-4 text-sm font-semibold text-ink hover:bg-ink-100"><MessageCircle className="h-4 w-4" aria-hidden />Open WhatsApp</a>}</div></>)}
          </div>
        ) : (
          <div className="space-y-4">{err && <Alert tone="error">{err}</Alert>}
            <Input label="Shopkeeper's email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} hint="This email is added to the sign-up allowlist so they can create the account. That is recorded in the audit log." />
            <Select label="How to send it" value={delivery} onChange={(e) => setDelivery(e.target.value as "link" | "email")}><option value="link">Copyable link (send it on WhatsApp)</option><option value="email">Email it now</option></Select>
            <p className="flex items-start gap-2 text-xs text-ink-500">{delivery === "email" ? <Mail className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /> : <MessageCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />}Whoever opens the link and signs up becomes the owner, and only while this business has no owner. They accept the terms and confirm their age themselves when they sign up.</p>
          </div>)}
      </Modal>
    </Card>
  );
}
