"use client";
import { Copy, Mail, MessageCircle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Card";
import { Input, Select, Textarea } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, ApiError, errorMessage } from "@/lib/api";
import { fmtDate } from "@/lib/format";

export interface CreatedBusiness { id: string; name: string; location: { id: string; name: string; city: string | null; review_url: string | null } }
interface ClaimOut { email: string; delivery: string; email_sent: boolean | null; link: string | null; whatsapp_url: string | null; expires_at: string }
interface Match { id: string; name: string; city: string | null; phone: string | null; origin: string; reasons: string[] }

const CATEGORIES = ["Clinic or hospital", "Dental clinic", "Pharmacy or medical store", "Restaurant or cafe", "Sweet shop or bakery", "Salon or spa", "Grocery or general store", "Clothing or footwear", "Electronics or mobile", "Gym or fitness", "Hotel or guest house", "School or coaching", "Other"];
const METHODS: [string, string][] = [["in_person", "In person, at the shop"], ["phone", "By phone"], ["whatsapp", "On WhatsApp"], ["paper", "On paper"], ["other", "Another way"]];

/**
 * Create a business for a shop that has no FlowQR login. Nothing here creates a user: the shopkeeper does not need an account for their cards, scans or review page to work.
 * If the business looks like one that already exists, the matches are shown and creating it needs an explicit "Create anyway" with a reason, which is recorded in the audit log.
 * `compact` is the version used inside the Assign card window.
 * Optionally the owner is invited right here (the same invitation as the business page's "Invite owner"): by email, or as a link shown once for WhatsApp. The business is created first; if the invitation
 * then fails (for example claims are switched off) the business still exists and the screen says so.
 */
export function AddBusinessForm({ onCreated, onCancel, compact = false }: { onCreated: (b: CreatedBusiness) => void; onCancel?: () => void; compact?: boolean }) {
  const [f, setF] = useState({ name: "", category: "", contact_name: "", phone: "", email: "", address: "", city: "", location_name: "", review_url: "", website: "" });
  const [invite, setInvite] = useState(false);
  const [delivery, setDelivery] = useState<"email" | "link">("link");
  const [done, setDone] = useState<{ b: CreatedBusiness; claim: ClaimOut | null; error: string | null } | null>(null);
  const toast = useToast();
  const [agree, setAgree] = useState(false);
  const [method, setMethod] = useState("in_person");
  const [agreeNote, setAgreeNote] = useState("");
  const [matches, setMatches] = useState<Match[] | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const warn = useRef<HTMLDivElement>(null);
  useEffect(() => { if (matches) warn.current?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }, [matches]);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => { setF({ ...f, [k]: e.target.value }); setMatches(null); };
  const clean = (v: string) => (v.trim() === "" ? null : v.trim());
  const ready = f.name.trim().length >= 2 && f.phone.trim().length >= 6 && f.city.trim().length >= 2 && (!matches || reason.trim().length >= 10) && (!invite || f.email.includes("@"));

  async function save() {
    setBusy(true); setErr(null);
    const body = {
      name: f.name.trim(), category: clean(f.category), contact_name: clean(f.contact_name), phone: f.phone.trim(), email: clean(f.email), address: clean(f.address), city: f.city.trim(),
      location_name: clean(f.location_name), review_url: clean(f.review_url), website: clean(f.website),
      agreement: agree ? { method, note: clean(agreeNote), confirm: true } : null, duplicate_reason: matches ? reason.trim() : null,
    };
    try {
      const b = await api<CreatedBusiness>("/admin/tenants", { method: "POST", body });
      if (!invite) { onCreated(b); return; }
      try { setDone({ b, claim: await api<ClaimOut>(`/admin/tenants/${b.id}/claim`, { method: "POST", body: { email: f.email.trim(), delivery } }), error: null }); }
      catch (e2) { setDone({ b, claim: null, error: errorMessage(e2) }); }  // the business exists; only the invitation failed
    } catch (e) {
      if (e instanceof ApiError && e.code === "duplicates_found") {
        setMatches((e.detail as { matches?: Match[] }).matches ?? []);
      } else setErr(errorMessage(e));
    } finally { setBusy(false); }
  }

  const copy = async (text: string) => { try { await navigator.clipboard.writeText(text); toast("Copied."); } catch { toast("Could not copy. Select the link and copy it.", "error"); } };
  if (done) {
    const { b, claim, error } = done;
    return (
      <div className="space-y-4 text-sm">
        <Alert tone="success">{b.name} was created.</Alert>
        {error && <Alert tone="warning">The business is saved, but the owner invitation was not created: {error} You can invite them later from the business page (Owner login).</Alert>}
        {claim && (claim.delivery === "email"
          ? (claim.email_sent ? <Alert tone="success">Invitation emailed to {claim.email}. It expires {fmtDate(claim.expires_at)}.</Alert> : <Alert tone="warning">The business is saved, but the email could not be sent. Open the business, revoke this invitation and send a link instead.</Alert>)
          : (<>
            <Alert tone="warning">This link is shown once and cannot be shown again. It expires {fmtDate(claim.expires_at)}.</Alert>
            <input readOnly aria-label="Invitation link" value={claim.link ?? ""} onFocus={(e) => e.currentTarget.select()} className="min-h-11 w-full rounded-xl border border-ink-200 px-3 text-xs" />
            <div className="flex flex-wrap gap-2"><Button variant="secondary" type="button" icon={<Copy className="h-4 w-4" />} onClick={() => void copy(claim.link ?? "")}>Copy link</Button>
              {claim.whatsapp_url && <a href={claim.whatsapp_url} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center gap-2 rounded-full bg-surface-2 px-4 text-sm font-semibold text-ink hover:bg-ink-100"><MessageCircle className="h-4 w-4" aria-hidden />Open WhatsApp</a>}</div>
          </>))}
        <div className="flex justify-end"><Button className="!rounded-full" onClick={() => onCreated(b)}>Continue</Button></div>
      </div>
    );
  }

  return (
    <form onSubmit={(e) => { e.preventDefault(); if (ready) void save(); }} className="space-y-4" noValidate>
      <p className="rounded-xl bg-surface-2 p-3 text-[13px] leading-5 text-ink-700"><b>No login is created.</b> The shopkeeper does not need a FlowQR account: their cards, scans and review page work from this record alone. You can invite them to claim it later, if you want.</p>
      {err && <Alert tone="error">{err}</Alert>}
      {matches && (
        <div className="space-y-3 rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900" role="alert" ref={warn}>
          <p className="font-semibold">This looks like a business that already exists</p>
          <ul className="space-y-1.5">{matches.map((m) => <li key={m.id} className="rounded-lg bg-white/70 p-2"><b>{m.name}</b>{m.city ? ` · ${m.city}` : ""}{m.phone ? ` · ${m.phone}` : ""}<span className="block text-xs">{m.reasons.join(" · ")} · {m.origin === "admin" ? "created by FlowQR staff" : "has its own account"}</span></li>)}</ul>
          <Textarea label="Why is this a different business? (required, saved in the audit log)" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} hint="At least 10 characters. If it is the same shop, cancel and use the existing one." />
        </div>
      )}
      <Input label="Business name" required value={f.name} onChange={set("name")} placeholder="e.g. Sharma Sweets" autoComplete="off" />
      <div className="grid gap-4 sm:grid-cols-2">
        <Input label="Shop phone number" required inputMode="tel" value={f.phone} onChange={set("phone")} placeholder="98765 43210" />
        <Input label="City" required value={f.city} onChange={set("city")} placeholder="e.g. Kanpur" />
      </div>
      <Input label="Business email (optional)" type="email" value={f.email} onChange={set("email")} hint="Also the address the owner invitation goes to, and the one they sign in with." />
      <Input label="Google review link" value={f.review_url} onChange={set("review_url")} placeholder="https://g.page/r/…/review" hint="Opens when a customer taps Continue to Google. You can add it later, but cards need it to work." />
      {!compact && (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Select label="Category" value={f.category} onChange={set("category")}><option value="">Choose…</option>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</Select>
            <Input label="Contact person (optional)" value={f.contact_name} onChange={set("contact_name")} />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Input label="Website (optional)" value={f.website} onChange={set("website")} placeholder="https://" />
          </div>
          <Input label="Address" value={f.address} onChange={set("address")} />
          <Input label="Location name" value={f.location_name} onChange={set("location_name")} hint="Leave empty to use the business name. You can add more locations afterwards." />
        </>
      )}
      <fieldset className="rounded-xl border border-line p-3">
        <label className="flex min-h-11 items-start gap-2.5 text-sm"><input type="checkbox" checked={invite} onChange={(e) => setInvite(e.target.checked)} className="mt-1 h-5 w-5" />
          <span><b>Invite the owner to take over this business</b> once it is saved. <span className="text-muted">They get their own login, with the cards and review page you set up. Optional: nothing needs it.</span></span></label>
        {invite && <div className="mt-3 space-y-2">
          <Select label="How to send it" value={delivery} onChange={(e) => setDelivery(e.target.value as "email" | "link")}><option value="link">Copyable link (send it on WhatsApp)</option><option value="email">Email it now</option></Select>
          <p className="flex items-start gap-2 text-xs text-ink-500">{delivery === "email" ? <Mail className="mt-0.5 h-4 w-4 shrink-0" aria-hidden /> : <MessageCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />}{f.email.includes("@") ? `Goes to ${f.email.trim()}. That address is added to the sign-up list (recorded in the audit log).` : "Enter the business email above to send the invitation."}</p>
        </div>}
      </fieldset>
      <fieldset className="rounded-xl border border-line p-3">
        <label className="flex min-h-11 items-start gap-2.5 text-sm"><input type="checkbox" checked={agree} onChange={(e) => setAgree(e.target.checked)} className="mt-1 h-5 w-5" />
          <span><b>I took this business through the FlowQR terms</b> and am recording that on their behalf. <span className="text-muted">Saved as your statement, with your name and the time. It is not the shopkeeper accepting the terms themselves, and says nothing about their age.</span></span></label>
        {agree && <div className="mt-3 grid gap-3 sm:grid-cols-2"><Select label="How" value={method} onChange={(e) => setMethod(e.target.value)}>{METHODS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</Select><Input label="Note (optional)" value={agreeNote} onChange={(e) => setAgreeNote(e.target.value)} /></div>}
      </fieldset>

      <div className="flex flex-wrap justify-end gap-2">
        {onCancel && <Button variant="secondary" className="!rounded-full" type="button" onClick={onCancel} disabled={busy}>Cancel</Button>}
        <Button className="!rounded-full" type="submit" loading={busy} disabled={!ready}>{matches ? "Create anyway" : "Save business"}</Button>
      </div>
    </form>
  );
}
