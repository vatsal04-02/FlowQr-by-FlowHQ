"use client";
import { ArrowRight, Building2, CheckCircle2, ChevronDown, ExternalLink, Globe, MapPin, Phone, Search, Star, X } from "lucide-react";
import clsx from "clsx";
import { useEffect, useRef, useState } from "react";
import { GoogleG } from "@/components/marketing/kit";
import { Button } from "@/components/ui/Button";
import { Alert, Spinner } from "@/components/ui/Card";
import { ErrorSummary, Input, Select } from "@/components/ui/Form";
import { api, ApiError, errorMessage } from "@/lib/api";
import { CATEGORIES, LANGS, TIMEZONES } from "@/lib/format";
import { emailRule, googleUrlRule, phoneRule, required, useForm } from "@/lib/form";
import { lookupPin, usePlaceSuggest, type PlaceDetails, type Suggestion } from "@/lib/places";
import type { Location, Tenant } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { PlaceCombobox } from "./Combobox";
import { Section, StepActions, StepCard, StepHeading } from "./Shell";

const STATES = ["Andaman and Nicobar Islands", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chandigarh", "Chhattisgarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa", "Gujarat",
  "Haryana", "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand", "Karnataka", "Kerala", "Ladakh", "Lakshadweep", "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland",
  "Odisha", "Puducherry", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal"];

type WebsiteInterest = "has_site" | "wants_site" | "not_now";
const WEBSITE_OPTIONS: { id: WebsiteInterest; title: string; body: string }[] = [
  { id: "has_site", title: "Yes, I have one", body: "You can add its address." },
  { id: "wants_site", title: "No, please build one", body: "FlowQR can build a simple website for you." },
  { id: "not_now", title: "No, not now", body: "Skip this. You can ask later." },
];

/**
 * Step 1: the business AND its first location, in one form. Creating it saves the business, then the location. Coming back to this step later (the business exists)
 * opens it pre-filled and saves the changes instead of adding a second one.
 */
export function BusinessStep({ tenant, place, onPlace, onDone }: { tenant: Tenant | null; place: PlaceDetails | null; onPlace: (p: PlaceDetails | null) => void; onDone: () => Promise<void> }) {
  const locs = useFetch<Location[]>(tenant ? "/locations" : null);
  if (tenant && locs.loading) return <StepCard><div className="grid place-items-center py-24"><Spinner /></div></StepCard>;
  const existing = locs.data?.[0] ?? null;
  return <BusinessForm key={existing?.id ?? "new"} tenant={tenant} existing={existing} place={place} onPlace={onPlace} onDone={onDone} />;
}

function BusinessForm({ tenant, existing, place, onPlace, onDone }: { tenant: Tenant | null; existing: Location | null; place: PlaceDetails | null; onPlace: (p: PlaceDetails | null) => void; onDone: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [picking, setPicking] = useState(false);
  const [pickingAddr, setPickingAddr] = useState(false);
  const [filledName, setFilledName] = useState<string | null>(null);  // text we put in a field ourselves must not start another search
  const [filledAddr, setFilledAddr] = useState<string | null>(null);
  const [pinNote, setPinNote] = useState<string | null>(null);
  const [linkFromGoogle, setLinkFromGoogle] = useState(false);
  const [softNote, setSoftNote] = useState<string | null>(null);
  const [needsVerify, setNeedsVerify] = useState(false);
  const [resent, setResent] = useState<string | null>(null);
  const [interest, setInterest] = useState<WebsiteInterest | null>(tenant?.website_interest ?? (tenant?.website ? "has_site" : null));  // "do you have a website?"
  const [interestError, setInterestError] = useState<string | null>(null);
  const tenantMade = useRef(!!tenant);  // the business exists once it has been saved, even if the location then fails: a retry must not create it twice
  const locId = useRef<string | null>(existing?.id ?? null);

  const f = useForm({
    name: tenant?.name ?? "", category: tenant?.category ?? "", phone: tenant?.phone ?? existing?.phone ?? "", email: tenant?.email ?? "", website: tenant?.website ?? "",
    address_line: existing?.address_line ?? "", city: existing?.city ?? "", state: existing?.state ?? "", postal_code: existing?.postal_code ?? "", review_url: existing?.review_url ?? "",
    location_name: existing?.name ?? "", language: tenant?.language ?? "en", timezone: tenant?.timezone ?? "Asia/Kolkata",
  }, {
    name: (v) => (String(v).trim().length >= 2 ? undefined : "Enter your business name"), category: required("Business type"),
    email: (v) => (String(v).trim() ? emailRule(v) : undefined), phone: phoneRule, review_url: googleUrlRule,
  });
  const cats = tenant?.category && !CATEGORIES.includes(tenant.category) ? [tenant.category, ...CATEGORIES] : CATEGORIES;
  const bizSuggest = usePlaceSuggest(f.values.name, "business", !picking && f.values.name !== filledName && f.values.name !== tenant?.name);
  const addrSuggest = usePlaceSuggest(f.values.address_line, "address", !pickingAddr && f.values.address_line !== (filledAddr ?? existing?.address_line));

  // A six-digit PIN fills the city and state that are still empty (India Post's directory, through our server).
  const pin = f.values.postal_code.trim();
  const seenPin = useRef(existing?.postal_code ?? "");
  useEffect(() => {
    if (!/^[1-9]\d{5}$/.test(pin) || pin === seenPin.current) return;
    seenPin.current = pin;
    const ctl = new AbortController();
    void lookupPin(pin, ctl.signal).then((info) => {
      if (!info || ctl.signal.aborted) return;
      let used = false;
      if (info.city && !f.values.city.trim()) { f.set("city", info.city); used = true; }
      if (info.state && !f.values.state.trim()) { f.set("state", info.state); used = true; }
      setPinNote(used ? `City and state filled in from PIN ${pin}.` : null);
    });
    return () => ctl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pin]);

  async function chooseBusiness(s: Suggestion) {
    setPicking(true); setSoftNote(null);
    const d = await bizSuggest.pick(s);
    setPicking(false);
    if (!d) { setFilledName(s.title); f.set("name", s.title); setSoftNote("We couldn't load the rest from Google just now. Please fill in the details below."); return; }
    onPlace(d);
    setFilledName(d.name); f.set("name", d.name);
    if (d.address_line) { setFilledAddr(d.address_line); f.set("address_line", d.address_line); }
    if (d.city) f.set("city", d.city);
    if (d.state) f.set("state", d.state);
    if (d.postal_code) { seenPin.current = d.postal_code; f.set("postal_code", d.postal_code); }
    if (d.phone) f.set("phone", d.phone);
    if (d.website) { f.set("website", d.website); setInterest((i) => i ?? "has_site"); setInterestError(null); }
    if (d.review_url) { f.set("review_url", d.review_url); setLinkFromGoogle(true); }
    if (d.category && CATEGORIES.includes(d.category)) f.set("category", d.category);
    else if (!f.values.category) f.set("category", "Other local business");
    if (!f.values.location_name.trim()) f.set("location_name", d.area ? `${d.area} branch` : "Main branch");
    setPinNote(null);
  }

  async function chooseAddress(s: Suggestion) {
    setPickingAddr(true);
    const d = await addrSuggest.pick(s);
    setPickingAddr(false);
    if (!d) { setFilledAddr(s.title); f.set("address_line", s.title); return; }
    const line = d.address_line || s.title;
    setFilledAddr(line); f.set("address_line", line);
    if (d.city) f.set("city", d.city);
    if (d.state) f.set("state", d.state);
    if (d.postal_code) { seenPin.current = d.postal_code; f.set("postal_code", d.postal_code); }
    setPinNote(null);
  }

  async function resend() {
    setResent(null);
    try {
      const r = await api<{ email_sent: boolean; detail: string }>("/auth/resend-verification", { method: "POST" });
      setResent(r.email_sent ? "Verification email sent. Check your inbox, open the link, then come back and press Continue." : r.detail);
    } catch (e) { setResent(errorMessage(e)); }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault(); f.setServerError(null);
    const valid = f.validateAll();
    if (!interest) setInterestError("Tell us whether you have a website. Choose one.");
    if (!valid || !interest) return;
    setBusy(true); setNeedsVerify(false);
    const v = f.values;
    const nul = (s: string) => s.trim() || null;
    const address = [v.address_line, v.city, v.state, v.postal_code].map((x) => x.trim()).filter(Boolean).join(", ");
    try {
      const tenantBody = { name: v.name.trim(), category: v.category, email: nul(v.email), phone: nul(v.phone), address: address || null, website: interest === "has_site" ? nul(v.website) : null, language: v.language, timezone: v.timezone };
      if (tenantMade.current) await api("/tenant", { method: "PATCH", body: tenantBody });
      else { await api("/tenants", { method: "POST", body: tenantBody }); tenantMade.current = true; }
      const locBody = { name: v.location_name.trim() || (place?.area ? `${place.area} branch` : "Main branch"), address_line: nul(v.address_line), city: nul(v.city), state: nul(v.state), postal_code: nul(v.postal_code), phone: nul(v.phone), review_url: nul(v.review_url) };
      if (locId.current) await api(`/locations/${locId.current}`, { method: "PATCH", body: locBody });
      else { const l = await api<Location>("/locations", { method: "POST", body: locBody }); locId.current = l.id; }
      if (interest !== tenant?.website_interest) await api("/tenant/website-interest", { method: "PUT", body: { interest } });
      await onDone();
    } catch (err) {
      // While registration is restricted (REGISTRATION_MODE closed/allowlist) the backend needs a verified address before it creates a business.
      if (err instanceof ApiError && err.code === "email_not_verified") setNeedsVerify(true);
      f.fail(errorMessage(err));
    } finally { setBusy(false); }
  }

  const link = f.values.review_url.trim();
  const linkOk = !!link && !googleUrlRule(link);
  const googleOn = bizSuggest.available;

  return (
    <StepCard>
      <StepHeading step={0} title={tenant ? "Your business" : "Tell us about your business"}>
        {tenant ? "Change anything you like, then continue." : googleOn ? "Search for your business on Google and we will fill in the rest. It takes a few seconds." : "This appears on your customers' review page."}
      </StepHeading>

      <form onSubmit={submit} noValidate className="mt-9 space-y-9">
        <ErrorSummary errors={f.errors} serverError={f.serverError} summaryRef={f.summaryRef} />
        {needsVerify && (
          <Alert tone="warning" title="Verify your email first" action={<Button type="button" variant="secondary" onClick={() => void resend()}>Send the link again</Button>}>
            {resent ?? "We sent a verification link when you registered. Open it, then press Continue again."}
          </Alert>
        )}

        <Section icon={Search} title="Find your business" hint={googleOn ? "Searches Google" : undefined}>
          <PlaceCombobox label="Business name" required value={f.values.name} onChange={(v) => f.set("name", v)} onBlurValue={() => f.bind("name").onBlur()} error={f.errors.name}
            suggestions={bizSuggest.items} loading={bizSuggest.loading} enabled={googleOn} picking={picking} onPick={(s) => void chooseBusiness(s)} name="organization"
            placeholder={googleOn ? "Start typing your business name" : "Your business name"} icon={<Building2 className="h-[18px] w-[18px]" strokeWidth={1.75} />} />

          {place && (
            <div role="status" className="fq-rise flex items-start gap-4 rounded-[20px] bg-gradient-to-br from-m-tint to-white p-4 ring-1 ring-m-accent/25">
              <GoogleG size={44} className="shadow-[var(--shadow-card)]" />
              <div className="min-w-0 flex-1 text-[14px]">
                <p className="inline-flex items-center gap-1.5 text-[12px] font-semibold uppercase tracking-[.08em] text-[#157347]"><CheckCircle2 className="h-3.5 w-3.5" aria-hidden />Found on Google</p>
                <p className="mt-1 text-[16px] font-semibold leading-snug text-m-ink">{place.name}</p>
                <p className="mt-0.5 text-m-ink2">{place.formatted_address.replace(/,\s*India$/i, "")}</p>
                <p className="mt-2 text-m-muted">We filled in the details below. Please check them.</p>
              </div>
              <button type="button" onClick={() => onPlace(null)} aria-label="Remove the Google listing" className="-m-1.5 grid h-10 w-10 shrink-0 place-items-center rounded-full text-m-muted hover:bg-white hover:text-m-ink"><X className="h-4 w-4" aria-hidden /></button>
            </div>
          )}
          {softNote && <p role="status" className="rounded-[14px] bg-m-tint p-3.5 text-[14px] text-m-ink">{softNote}</p>}

          <Select label="Business type" required {...f.bind("category")}>
            <option value="" disabled>Choose what you do</option>
            {cats.map((c) => <option key={c}>{c}</option>)}
          </Select>
        </Section>

        <Section icon={MapPin} title="Where customers find you" delay={80}>
          <PlaceCombobox label="Street address" value={f.values.address_line} onChange={(v) => f.set("address_line", v)} suggestions={addrSuggest.items} loading={addrSuggest.loading}
            enabled={addrSuggest.available} picking={pickingAddr} onPick={(s) => void chooseAddress(s)} name="street-address" autoComplete="street-address" placeholder="Building, street, area"
            hint={addrSuggest.available ? "Start typing to pick your address and fill in the city, state and PIN code." : undefined} />
          <div className="grid gap-5 sm:grid-cols-[150px_1fr_1fr]">
            <Input label="PIN code" inputMode="numeric" autoComplete="postal-code" maxLength={6} placeholder="226001" {...f.bind("postal_code")} onChange={(e) => f.set("postal_code", e.target.value.replace(/\D/g, "").slice(0, 6))} />
            <Input label="City" autoComplete="address-level2" {...f.bind("city")} />
            <Input label="State" autoComplete="address-level1" list="in-states" {...f.bind("state")} />
          </div>
          <datalist id="in-states">{STATES.map((s) => <option key={s} value={s} />)}</datalist>
          {pinNote && <p role="status" className="-mt-2 flex items-center gap-2 text-[13px] text-[#157347]"><CheckCircle2 className="h-4 w-4" aria-hidden />{pinNote}</p>}
        </Section>

        <Section icon={Phone} title="How to reach you" hint="All optional" delay={160}>
          <div className="grid gap-5 sm:grid-cols-2">
            <Input label="Phone" type="tel" inputMode="tel" autoComplete="tel-national" placeholder="98765 43210" {...f.bind("phone")} />
            <Input label="Business email" type="email" inputMode="email" autoComplete="email" {...f.bind("email")} />
          </div>
        </Section>

        <Section icon={Globe} title="Do you have a website?" delay={200}>
          <fieldset aria-describedby={interestError ? "interest-err" : undefined}>
            <legend className="sr-only">Do you have a website?</legend>
            <div className="grid gap-3 sm:grid-cols-3">
              {WEBSITE_OPTIONS.map((o) => {
                const on = interest === o.id;
                return (
                  <label key={o.id} className={clsx("flex min-h-[88px] cursor-pointer flex-col gap-1 rounded-[18px] p-4 ring-1 transition-[box-shadow,background-color] duration-200 focus-within:ring-2 focus-within:ring-m-accentStrong",
                    on ? "bg-m-tint ring-2 ring-m-accent" : "bg-white ring-m-line hover:ring-m-ink/25")}>
                    <input type="radio" name="website_interest" value={o.id} checked={on} onChange={() => { setInterest(o.id); setInterestError(null); }} className="sr-only" />
                    <span className="flex items-center justify-between gap-2 text-[15px] font-semibold text-m-ink">{o.title}<span aria-hidden className={clsx("grid h-5 w-5 shrink-0 place-items-center rounded-full ring-1", on ? "bg-m-accent text-m-ink ring-m-accent" : "bg-white ring-m-muted2")}>{on && <CheckCircle2 className="h-3.5 w-3.5" strokeWidth={3} />}</span></span>
                    <span className="text-[13px] leading-snug text-m-ink2">{o.body}</span>
                  </label>
                );
              })}
            </div>
            {interestError && <p id="interest-err" role="alert" className="mt-2 text-[13px] font-medium text-[#B42318]">{interestError}</p>}
          </fieldset>
          {interest === "has_site" && <Input label="Your website address" inputMode="url" autoComplete="url" placeholder="yourbusiness.in" hint="Optional. We show it on your Google profile checks and your review page." {...f.bind("website")} />}
          {interest === "wants_site" && <p role="status" className="rounded-[14px] bg-m-tint p-3.5 text-[14px] leading-relaxed text-m-ink">Good. Our team will build a simple website for your business and get in touch to go through it with you. Choosing this creates nothing and charges nothing, and you can change your mind any time.</p>}
        </Section>

        <Section icon={Star} title="Your Google review link" hint="Optional" delay={240}>
          <div>
            <Input label="Review link" inputMode="url" placeholder="https://g.page/r/…/review" hint={linkFromGoogle && linkOk ? undefined : "Paste it now or add it later. Your cards keep working when you change it."}
              {...f.bind("review_url")} onChange={(e) => { setLinkFromGoogle(false); f.set("review_url", e.target.value); }} />
            {linkOk && (
              <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px]">
                {linkFromGoogle && <span className="inline-flex items-center gap-1.5 text-[#157347]"><CheckCircle2 className="h-4 w-4" aria-hidden />Found automatically from your Google listing</span>}
                <a href={link} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-9 items-center gap-1 font-medium text-m-accentStrong underline underline-offset-2">Test the link<ExternalLink className="h-3.5 w-3.5" aria-hidden /></a>
              </p>
            )}
          </div>
        </Section>

        <details className="group rounded-[18px] border border-m-line bg-white/60 px-4 py-3 open:bg-white">
          <summary className="flex min-h-9 cursor-pointer list-none items-center justify-between gap-3 text-[14px] font-medium text-m-ink">
            <span>More options <span className="font-normal text-m-muted">· location name, language, time zone</span></span>
            <ChevronDown aria-hidden className="h-4 w-4 shrink-0 text-m-muted transition-transform group-open:rotate-180" />
          </summary>
          <div className="mt-4 space-y-5">
            <Input label="Location name" placeholder="Main branch" hint="Shown to you and your team so you can tell branches apart. You can add more locations later." {...f.bind("location_name")} />
            <div className="grid gap-5 sm:grid-cols-2">
              <Select label="Preferred language" hint="Used for AI replies by default." {...f.bind("language")}>{LANGS.map((l) => <option key={l.v} value={l.v}>{l.l}</option>)}</Select>
              <Select label="Time zone" {...f.bind("timezone")}>{TIMEZONES.map((t) => <option key={t}>{t}</option>)}</Select>
            </div>
          </div>
        </details>

        <StepActions>
          <Button type="submit" variant="brand" size="lg" className="w-full sm:w-auto sm:min-w-[220px]" loading={busy}>{tenant ? "Save and continue" : "Continue"} <ArrowRight className="h-4 w-4" aria-hidden /></Button>
        </StepActions>
      </form>
    </StepCard>
  );
}
