"use client";
import clsx from "clsx";
import { Check, Link2, Pencil } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Logo } from "@/components/ui/Brand";
import { Button } from "@/components/ui/Button";
import { Alert, Card, Spinner } from "@/components/ui/Card";
import { ErrorSummary, Input, Select } from "@/components/ui/Form";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { CATEGORIES, LANGS, TIMEZONES } from "@/lib/format";
import { emailRule, googleUrlRule, phoneRule, required, useForm } from "@/lib/form";
import type { Location } from "@/lib/types";

const STEPS = ["Your business", "First location", "Google reviews"];

export default function Onboarding() {
  const { me, tenant, loading, refresh } = useAuth();
  const router = useRouter();
  const [step, setStep] = useState<number | null>(null);

  useEffect(() => {
    if (loading) return;
    if (!me) { router.replace("/login"); return; }
    if (tenant?.onboarding_completed) { router.replace("/dashboard"); return; }
    if (step !== null) return;
    if (!tenant) { setStep(0); return; }
    api<Location[]>("/locations").then((l) => setStep(l.length ? 2 : 1)).catch(() => setStep(1));
  }, [loading, me, tenant, router, step]);

  if (step === null) return <div className="grid min-h-dvh place-items-center"><Spinner /></div>;
  return (
    <div className="min-h-dvh bg-ink-50/60">
      <header className="border-b border-ink-100 bg-white"><div className="container-page flex items-center justify-between py-3"><Logo /><p className="text-sm text-ink-500">{me?.user.email}</p></div></header>
      <main className="mx-auto max-w-xl px-4 py-8 sm:py-12">
        <ol className="mb-8 flex items-center gap-2" aria-label="Progress">
          {STEPS.map((s, i) => (
            <li key={s} className="flex flex-1 items-center gap-2" aria-current={i === step ? "step" : undefined}>
              <span className={clsx("grid h-8 w-8 shrink-0 place-items-center rounded-full text-sm font-bold", i < step ? "bg-g-green text-white" : i === step ? "bg-brand-600 text-white" : "bg-ink-100 text-ink-500")}>
                {i < step ? <Check className="h-4 w-4" aria-label="done" /> : i + 1}
              </span>
              <span className={clsx("hidden text-sm font-semibold sm:block", i === step ? "text-ink" : "text-ink-400")}>{s}</span>
              {i < STEPS.length - 1 && <span className="h-px flex-1 bg-ink-200" aria-hidden />}
            </li>
          ))}
        </ol>
        {step === 0 && <BusinessStep onDone={async () => { await refresh(); setStep(1); }} />}
        {step === 1 && <LocationStep onDone={() => setStep(2)} />}
        {step === 2 && <GoogleStep />}
      </main>
    </div>
  );
}

function BusinessStep({ onDone }: { onDone: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const f = useForm({ name: "", category: CATEGORIES[0], email: "", phone: "", address: "", website: "", language: "en", timezone: "Asia/Kolkata" }, {
    name: required("Business name"), category: required("Category"), email: (v) => (String(v).trim() ? emailRule(v) : undefined), phone: phoneRule,
  });
  async function submit(e: React.FormEvent) {
    e.preventDefault(); f.setServerError(null);
    if (!f.validateAll()) return;
    setBusy(true);
    try {
      const v = f.values;
      await api("/tenants", { method: "POST", body: { ...v, name: v.name.trim(), email: v.email.trim() || null, phone: v.phone.trim() || null, address: v.address.trim() || null, website: v.website.trim() || null } });
      await onDone();
    } catch (err) { f.fail(errorMessage(err)); } finally { setBusy(false); }
  }
  return (
    <Card>
      <h1 className="text-2xl font-semibold">Tell us about your business</h1>
      <p className="mt-1 text-ink-500">This appears on your customers' review page.</p>
      <form onSubmit={submit} noValidate className="mt-6 space-y-4">
        <ErrorSummary errors={f.errors} serverError={f.serverError} summaryRef={f.summaryRef} />
        <Input label="Business name" required placeholder="e.g. Geeta Krishna Physiotherapy" {...f.bind("name")} />
        <Select label="Business category" required {...f.bind("category")}>{CATEGORIES.map((c) => <option key={c}>{c}</option>)}</Select>
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Business email" type="email" inputMode="email" {...f.bind("email")} />
          <Input label="Phone" type="tel" inputMode="tel" placeholder="98765 43210" {...f.bind("phone")} />
        </div>
        <Input label="Address" autoComplete="street-address" {...f.bind("address")} />
        <Input label="Website" inputMode="url" placeholder="yourclinic.in" {...f.bind("website")} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Select label="Preferred language" hint="Used for AI replies by default." {...f.bind("language")}>{LANGS.map((l) => <option key={l.v} value={l.v}>{l.l}</option>)}</Select>
          <Select label="Time zone" {...f.bind("timezone")}>{TIMEZONES.map((t) => <option key={t}>{t}</option>)}</Select>
        </div>
        <Button type="submit" size="lg" className="w-full" loading={busy}>Continue</Button>
      </form>
    </Card>
  );
}

function LocationStep({ onDone }: { onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const f = useForm({ name: "", address_line: "", city: "", state: "", postal_code: "", phone: "", review_url: "" }, {
    name: required("Location name"), phone: phoneRule, review_url: googleUrlRule,
  });
  async function submit(e: React.FormEvent) {
    e.preventDefault(); f.setServerError(null);
    if (!f.validateAll()) return;
    setBusy(true);
    try {
      const body = Object.fromEntries(Object.entries(f.values).map(([k, v]) => [k, String(v).trim() || null]));
      await api("/locations", { method: "POST", body });
      onDone();
    } catch (err) { f.fail(errorMessage(err)); } finally { setBusy(false); }
  }
  return (
    <Card>
      <h1 className="text-2xl font-semibold">Add your first location</h1>
      <p className="mt-1 text-ink-500">Each branch gets its own cards. You can add more later.</p>
      <form onSubmit={submit} noValidate className="mt-6 space-y-4">
        <ErrorSummary errors={f.errors} serverError={f.serverError} summaryRef={f.summaryRef} />
        <Input label="Location name" required placeholder="e.g. Gomti Nagar branch" {...f.bind("name")} />
        <Input label="Street address" {...f.bind("address_line")} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="City" {...f.bind("city")} /><Input label="State" {...f.bind("state")} />
          <Input label="PIN code" inputMode="numeric" {...f.bind("postal_code")} /><Input label="Phone" type="tel" inputMode="tel" {...f.bind("phone")} />
        </div>
        <Input label="Google review link (optional)" inputMode="url" placeholder="https://g.page/r/…/review"
          hint="Paste it now or add it later. Cards keep working when you change it." {...f.bind("review_url")} />
        <Button type="submit" size="lg" className="w-full" loading={busy}>Continue</Button>
      </form>
    </Card>
  );
}

function GoogleStep() {
  const { refresh } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState<"manual" | "google" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function finish(next: "manual" | "google") {
    setBusy(next); setNotice(null);
    try {
      await api("/tenant/complete-onboarding", { method: "POST" });
      if (next === "google") {
        try {
          const { auth_url } = await api<{ auth_url: string }>("/google/connect", { method: "POST" });
          window.location.href = auth_url;
          return;
        } catch (e) {
          if (e instanceof ApiError && e.code === "google_config_pending") {
            await refresh();
            router.replace("/google");
            return;
          }
          throw e;
        }
      }
      await refresh();
      router.replace("/dashboard");
    } catch (e) { setNotice(errorMessage(e)); setBusy(null); }
  }

  return (
    <Card>
      <h1 className="text-2xl font-semibold">How do you want to collect reviews?</h1>
      <p className="mt-1 text-ink-500">You can switch any time. Your QR/NFC cards work either way.</p>
      {notice && <div className="mt-4"><Alert tone="error">{notice}</Alert></div>}
      <div className="mt-6 grid gap-3">
        <button disabled={!!busy} onClick={() => void finish("manual")} className="tap flex items-start gap-4 rounded-2xl border-2 border-ink-100 p-4 text-left transition-colors hover:border-brand-300 hover:bg-brand-50/40 disabled:opacity-60">
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-flow-50 text-flow-700"><Pencil className="h-5 w-5" aria-hidden /></span>
          <span><span className="block font-semibold">Use my Google review link</span><span className="mt-0.5 block text-sm text-ink-500">Fastest. Cards, AI writing help and scan analytics work immediately.</span></span>
        </button>
        <button disabled={!!busy} onClick={() => void finish("google")} className="tap flex items-start gap-4 rounded-2xl border-2 border-ink-100 p-4 text-left transition-colors hover:border-brand-300 hover:bg-brand-50/40 disabled:opacity-60">
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-brand-50 text-brand-700"><Link2 className="h-5 w-5" aria-hidden /></span>
          <span><span className="block font-semibold">Connect my Google Business Profile</span><span className="mt-0.5 block text-sm text-ink-500">Also syncs reviews and lets you approve AI-drafted replies. Requires Google access approval for FlowQR.</span></span>
        </button>
      </div>
      {busy && <p className="mt-4 text-center text-sm text-ink-500">Setting things up…</p>}
    </Card>
  );
}
