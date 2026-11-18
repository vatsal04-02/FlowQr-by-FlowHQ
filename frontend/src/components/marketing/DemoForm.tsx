"use client";
import { CheckCircle2, Loader2, Mail, MessageCircle } from "lucide-react";
import { useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { track } from "@/lib/track";
import { useFetch } from "@/lib/use-api";
import { en } from "@/content/marketing/en";

const TYPES: [string, string][] = [["clinic", "Clinic"], ["dental", "Dental"], ["salon", "Salon"], ["restaurant", "Restaurant or café"], ["gym", "Gym"], ["coaching", "Coaching"], ["retail", "Retail"], ["hotel", "Hotel"], ["other", "Other"]];
const TIMES = ["Weekday mornings", "Weekday afternoons", "Weekday evenings", "Saturday"];
type F = { name: string; business_name: string; city: string; business_type: string; locations: string; phone: string; whatsapp_ok: boolean; preferred_time: string; website: string };
const EMPTY: F = { name: "", business_name: "", city: "", business_type: "", locations: "1", phone: "", whatsapp_ok: false, preferred_time: "", website: "" }; // never pre-ticked: consent to WhatsApp messages must be an active choice

function validate(f: F) {
  const e: Partial<Record<keyof F, string>> = {};
  if (f.name.trim().length < 2) e.name = "Enter your name.";
  if (f.business_name.trim().length < 2) e.business_name = "Enter your business name.";
  if (f.city.trim().length < 2) e.city = "Enter your city.";
  if (!f.business_type) e.business_type = "Choose a business type.";
  const n = Number(f.locations); if (!Number.isInteger(n) || n < 1 || n > 500) e.locations = "Enter a number from 1 to 500.";
  if (!/^[6-9]\d{9}$/.test(f.phone.replace(/[\s-]/g, "").replace(/^(\+91|0)/, ""))) e.phone = "Enter a 10-digit Indian mobile number.";
  return e;
}

/** The book-a-demo form. Saves to POST /public/leads (validated, rate limited, honeypot). Real success and error states. */
export function DemoForm() {
  const c = en.demo;
  const [f, setF] = useState<F>(EMPTY);
  const [errors, setErrors] = useState<Partial<Record<keyof F, string>>>({});
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const { data: info } = useFetch<{ support_email: string | null }>("/legal/info");
  const wa = process.env.NEXT_PUBLIC_WHATSAPP_NUMBER;
  const set = (k: keyof F) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF((s) => ({ ...s, [k]: e.target.type === "checkbox" ? (e.target as HTMLInputElement).checked : e.target.value }));

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    setFailed(null);
    const e = validate(f); setErrors(e);
    if (Object.keys(e).length) { document.getElementById(`f-${Object.keys(e)[0]}`)?.focus(); return; }
    setBusy(true);
    try {
      await api("/public/leads", { method: "POST", body: { ...f, locations: Number(f.locations), preferred_time: f.preferred_time || null, website: f.website || null } });
      track("demo_submit", { business_type: f.business_type });
      setDone(true);
    } catch (err) { setFailed(errorMessage(err)); } finally { setBusy(false); }
  }

  const field = "h-11 w-full rounded-[10px] bg-m-surface px-3.5 text-[15px] font-medium text-m-ink outline-none transition focus:shadow-[0_0_0_1px_rgb(var(--m-accent)),0_0_0_4px_rgba(254,106,5,.15)] aria-[invalid=true]:shadow-[0_0_0_1px_#B42318]";
  // A plain function, not a component: a component defined here would remount its input on every keystroke.
  const L = ({ k, label, children }: { k: keyof F; label: string; children: React.ReactNode }) => (
    <label key={k} className="block"><span className="mb-2 block t-small text-m-muted">{label}</span>{children}{errors[k] && <span id={`f-${k}-e`} className="mt-1.5 block text-[12.5px] text-[#B42318]">{errors[k]}</span>}</label>
  );
  const a = (k: keyof F) => ({ id: `f-${k}`, "aria-invalid": errors[k] ? true : undefined, "aria-describedby": errors[k] ? `f-${k}-e` : undefined });

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px] lg:gap-8">
      {done ? (
        <div role="status" className="mkt-card flex flex-col items-start p-8">
          <CheckCircle2 className="h-10 w-10 text-[#157347]" strokeWidth={1.5} aria-hidden />
          <h2 className="mt-5 t-h3 text-m-ink">{c.success[0]}</h2>
          <p className="mt-3 max-w-[420px] text-[15px] text-m-muted">{c.success[1]}</p>
        </div>
      ) : (
        <form onSubmit={submit} noValidate className="grid gap-4 sm:grid-cols-2">
          {L({ k: "name", label: "Your name", children: <input {...a("name")} className={field} autoComplete="name" value={f.name} onChange={set("name")} /> })}
          {L({ k: "business_name", label: "Business name", children: <input {...a("business_name")} className={field} autoComplete="organization" value={f.business_name} onChange={set("business_name")} /> })}
          {L({ k: "city", label: "City", children: <input {...a("city")} className={field} autoComplete="address-level2" value={f.city} onChange={set("city")} /> })}
          {L({ k: "business_type", label: "Business type", children: <select {...a("business_type")} className={field} value={f.business_type} onChange={set("business_type")}><option value="">Choose one</option>{TYPES.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select> })}
          {L({ k: "locations", label: "Number of locations", children: <input {...a("locations")} className={field} inputMode="numeric" value={f.locations} onChange={set("locations")} /> })}
          {L({ k: "phone", label: "Mobile number", children: <span className="relative block"><span className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-[15px] font-medium text-m-muted">+91</span><input {...a("phone")} className={`${field} pl-12`} type="tel" inputMode="tel" autoComplete="tel-national" placeholder="98765 43210" value={f.phone} onChange={set("phone")} /></span> })}
          {L({ k: "preferred_time", label: "Preferred time (optional)", children: <select {...a("preferred_time")} className={field} value={f.preferred_time} onChange={set("preferred_time")}><option value="">Any time</option>{TIMES.map((t) => <option key={t}>{t}</option>)}</select> })}
          <label className="flex min-h-11 items-center gap-3 self-end t-small text-m-ink2"><input type="checkbox" checked={f.whatsapp_ok} onChange={set("whatsapp_ok")} className="h-5 w-5 accent-[#C94C00]" />You can also message me on WhatsApp</label>
          {/* Honeypot: hidden from people and screen readers; bots fill it. */}
          <div aria-hidden className="absolute -left-[9999px] h-px w-px overflow-hidden"><label>Website<input tabIndex={-1} autoComplete="off" value={f.website} onChange={set("website")} /></label></div>
          {failed && <p role="alert" className="rounded-[10px] bg-[#FDECEA] p-3 text-[13px] text-[#8A1C12] sm:col-span-2">{failed}</p>}
          <div className="sm:col-span-2">
            <button type="submit" disabled={busy} className="inline-flex h-11 items-center gap-2 rounded-full bg-m-accent px-6 text-[14px] font-medium text-m-ink transition hover:bg-[#F06000] disabled:opacity-60">
              {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}Book my demo
            </button>
            <p className="mt-3 text-[12.5px] text-m-muted">We use these details only to contact you about FlowQR. See our <a href="/privacy" className="underline">Privacy policy</a>.</p>
          </div>
        </form>
      )}
      <aside className="mkt-card self-start p-7">
        <p className="text-[17px] font-medium tracking-[-.02em] text-m-ink">What happens next</p>
        <ol className="mt-5 space-y-4">{c.next.map(([t, b], i) => <li key={t} className="flex gap-3"><span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-m-tint text-[12px] font-semibold text-m-accentStrong">{i + 1}</span><span><span className="block t-small text-m-ink">{t}</span><span className="block text-[13px] text-m-muted">{b}</span></span></li>)}</ol>
        <div className="mt-7 flex flex-col gap-2">
          {wa && <a href={`https://wa.me/${wa.replace(/\D/g, "")}`} target="_blank" rel="noopener noreferrer" className="inline-flex min-h-11 items-center gap-2 rounded-full border border-m-ink/70 px-5 t-small text-m-ink hover:bg-m-ink/[.04]"><MessageCircle className="h-4 w-4" strokeWidth={1.5} aria-hidden />Message us on WhatsApp</a>}
          {info?.support_email && <a href={`mailto:${info.support_email}`} className="inline-flex min-h-11 items-center gap-2 rounded-full border border-m-ink/70 px-5 t-small text-m-ink hover:bg-m-ink/[.04]"><Mail className="h-4 w-4" strokeWidth={1.5} aria-hidden />{info.support_email}</a>}
        </div>
      </aside>
    </div>
  );
}
