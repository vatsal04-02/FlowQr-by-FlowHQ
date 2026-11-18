"use client";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Card";
import { Input, Select, Textarea } from "@/components/ui/Form";
import { api, ApiError, errorMessage } from "@/lib/api";

export interface CreatedBusiness { id: string; name: string; location: { id: string; name: string; city: string | null; review_url: string | null } }
interface Match { id: string; name: string; city: string | null; phone: string | null; origin: string; reasons: string[] }

const CATEGORIES = ["Clinic or hospital", "Dental clinic", "Pharmacy or medical store", "Restaurant or cafe", "Sweet shop or bakery", "Salon or spa", "Grocery or general store", "Clothing or footwear", "Electronics or mobile", "Gym or fitness", "Hotel or guest house", "School or coaching", "Other"];
const METHODS: [string, string][] = [["in_person", "In person, at the shop"], ["phone", "By phone"], ["whatsapp", "On WhatsApp"], ["paper", "On paper"], ["other", "Another way"]];

/**
 * Create a business for a shop that has no FlowQR login. Nothing here creates a user: the shopkeeper does not need an account for their cards, scans or review page to work.
 * If the business looks like one that already exists, the matches are shown and creating it needs an explicit "Create anyway" with a reason, which is recorded in the audit log.
 * `compact` is the version used inside the Assign card window.
 */
export function AddBusinessForm({ onCreated, onCancel, compact = false }: { onCreated: (b: CreatedBusiness) => void; onCancel?: () => void; compact?: boolean }) {
  const [f, setF] = useState({ name: "", category: "", contact_name: "", phone: "", email: "", address: "", city: "", location_name: "", review_url: "", website: "" });
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
  const ready = f.name.trim().length >= 2 && f.phone.trim().length >= 6 && f.city.trim().length >= 2 && (!matches || reason.trim().length >= 10);

  async function save() {
    setBusy(true); setErr(null);
    const body = {
      name: f.name.trim(), category: clean(f.category), contact_name: clean(f.contact_name), phone: f.phone.trim(), email: clean(f.email), address: clean(f.address), city: f.city.trim(),
      location_name: clean(f.location_name), review_url: clean(f.review_url), website: clean(f.website),
      agreement: agree ? { method, note: clean(agreeNote), confirm: true } : null, duplicate_reason: matches ? reason.trim() : null,
    };
    try { const b = await api<CreatedBusiness>("/admin/tenants", { method: "POST", body }); onCreated(b); }
    catch (e) {
      if (e instanceof ApiError && e.code === "duplicates_found") {
        setMatches((e.detail as { matches?: Match[] }).matches ?? []);
      } else setErr(errorMessage(e));
    } finally { setBusy(false); }
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
      <Input label="Google review link" value={f.review_url} onChange={set("review_url")} placeholder="https://g.page/r/…/review" hint="Opens when a customer taps Continue to Google. You can add it later, but cards need it to work." />
      {!compact && (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Select label="Category" value={f.category} onChange={set("category")}><option value="">Choose…</option>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</Select>
            <Input label="Contact person (optional)" value={f.contact_name} onChange={set("contact_name")} />
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Input label="Email (optional)" type="email" value={f.email} onChange={set("email")} />
            <Input label="Website (optional)" value={f.website} onChange={set("website")} placeholder="https://" />
          </div>
          <Input label="Address" value={f.address} onChange={set("address")} />
          <Input label="Location name" value={f.location_name} onChange={set("location_name")} hint="Leave empty to use the business name. You can add more locations afterwards." />
        </>
      )}
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
