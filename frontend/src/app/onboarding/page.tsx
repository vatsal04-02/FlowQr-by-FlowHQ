"use client";
import clsx from "clsx";
import { Check, Link2, LogOut, Pencil, QrCode } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Logo } from "@/components/ui/Brand";
import { Button } from "@/components/ui/Button";
import { Alert, Badge, Card, Spinner } from "@/components/ui/Card";
import { ErrorSummary, Input, Select } from "@/components/ui/Form";
import { api, ApiError, errorMessage } from "@/lib/api";
import { PlanAuthorizationStep } from "@/components/billing/PlanAuthorizationStep";
import { useAuth } from "@/lib/auth";
import { CATEGORIES, LANGS, TIMEZONES } from "@/lib/format";
import { emailRule, googleUrlRule, phoneRule, required, useForm } from "@/lib/form";
import { useFetch } from "@/lib/use-api";
import type { Location, PlansResponse, SubscriptionInfo } from "@/lib/types";

const ALL_STEPS = [["business", "Your business"], ["location", "First location"], ["plan", "Plan and payment"], ["google", "Google reviews"], ["ready", "First review page"]] as const;
type StepId = (typeof ALL_STEPS)[number][0];

export default function Onboarding() {
  const { me, tenant, loading, refresh, logout } = useAuth();
  const router = useRouter();
  const plans = useFetch<PlansResponse>("/billing/plans");
  const [stepId, setStepId] = useState<StepId | null>(null);
  // The payment step exists only when the server says a payment authorisation is required before the free trial. Where it is not, onboarding is exactly as it was.
  const needsPlan = !!plans.data?.billing.mandate_required;
  const steps = ALL_STEPS.filter(([id]) => id !== "plan" || needsPlan);
  const after = (id: StepId): StepId => steps[Math.min(steps.findIndex(([i]) => i === id) + 1, steps.length - 1)][0];

  useEffect(() => {
    if (loading || (plans.loading && !plans.data)) return;
    if (!me) { router.replace("/login"); return; }
    if (tenant?.onboarding_completed) { router.replace("/overview"); return; }
    if (stepId !== null) return;
    if (!tenant) { setStepId("business"); return; }
    // progress is derived from the server (a location exists, the subscription is still awaiting authorisation), so leaving and coming back resumes in the right place
    Promise.all([api<Location[]>("/locations"), api<SubscriptionInfo>("/billing/subscription")])
      .then(([l, s]) => setStepId(!l.length ? "location" : needsPlan && s.status === "incomplete" ? "plan" : "google"))
      .catch(() => setStepId("location"));
  }, [loading, me, tenant, router, stepId, plans.loading, plans.data, needsPlan]);

  if (stepId === null) return <div className="grid min-h-dvh place-items-center"><Spinner /></div>;
  const step = steps.findIndex(([id]) => id === stepId);
  return (
    <div className="min-h-dvh bg-ink-50">
      <header className="border-b border-ink-100 bg-white"><div className="container-page flex items-center justify-between py-3"><Logo /><div className="flex items-center gap-3"><p className="hidden text-sm text-ink-500 sm:block">{me?.user.email}</p><button type="button" onClick={() => void logout()} className="tap inline-flex items-center gap-1.5 rounded-full px-3 text-sm font-semibold text-ink-700 hover:bg-ink-100"><LogOut className="h-4 w-4" aria-hidden />Sign out</button></div></div></header>
      <main className="mx-auto max-w-xl px-4 py-8 sm:py-12">
        <ol className="mb-8 flex items-center gap-2" aria-label="Progress">
          {steps.map(([id, label], i) => (
            <li key={id} className="flex flex-1 items-center gap-2" aria-current={i === step ? "step" : undefined}>
              <span className={clsx("grid h-8 w-8 shrink-0 place-items-center rounded-full text-sm font-bold", i < step ? "bg-ok text-white" : i === step ? "bg-brand-600 text-navy" : "bg-ink-100 text-ink-500")}>
                {i < step ? <Check className="h-4 w-4" aria-label="done" /> : i + 1}
              </span>
              <span className={clsx("hidden text-sm font-semibold sm:block", i === step ? "text-ink" : "text-ink-400")}>{label}</span>
              {i < steps.length - 1 && <span className="h-px flex-1 bg-ink-200" aria-hidden />}
            </li>
          ))}
        </ol>
        {stepId === "business" && <BusinessStep onDone={async () => { await refresh(); setStepId("location"); }} />}
        {stepId === "location" && <LocationStep onDone={() => setStepId(after("location"))} />}
        {stepId === "plan" && <PlanAuthorizationStep onDone={() => setStepId("google")} />}
        {stepId === "google" && <GoogleStep onManual={() => setStepId("ready")} />}
        {stepId === "ready" && <ReadyStep />}
      </main>
    </div>
  );
}

function BusinessStep({ onDone }: { onDone: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [needsVerify, setNeedsVerify] = useState(false);
  const [resent, setResent] = useState<string | null>(null);
  async function resend() {
    setResent(null);
    try {
      const r = await api<{ email_sent: boolean; detail: string }>("/auth/resend-verification", { method: "POST" });
      setResent(r.email_sent ? "Verification email sent. Check your inbox, open the link, then come back and press Continue." : r.detail);
    } catch (e) { setResent(errorMessage(e)); }
  }
  const f = useForm({ name: "", category: CATEGORIES[0], email: "", phone: "", address: "", website: "", language: "en", timezone: "Asia/Kolkata" }, {
    name: required("Business name"), category: required("Category"), email: (v) => (String(v).trim() ? emailRule(v) : undefined), phone: phoneRule,
  });
  async function submit(e: React.FormEvent) {
    e.preventDefault(); f.setServerError(null);
    if (!f.validateAll()) return;
    setBusy(true);
    setNeedsVerify(false);
    try {
      const v = f.values;
      await api("/tenants", { method: "POST", body: { ...v, name: v.name.trim(), email: v.email.trim() || null, phone: v.phone.trim() || null, address: v.address.trim() || null, website: v.website.trim() || null } });
      await onDone();
    } catch (err) {
      // While registration is restricted (REGISTRATION_MODE closed/allowlist) the backend needs a verified address before it creates a business.
      if (err instanceof ApiError && err.code === "email_not_verified") setNeedsVerify(true);
      f.fail(errorMessage(err));
    } finally { setBusy(false); }
  }
  return (
    <Card>
      <h1 className="text-2xl font-semibold">Tell us about your business</h1>
      <p className="mt-1 text-ink-500">This appears on your customers' review page.</p>
      <form onSubmit={submit} noValidate className="mt-6 space-y-4">
        <ErrorSummary errors={f.errors} serverError={f.serverError} summaryRef={f.summaryRef} />
        {needsVerify && (
          <Alert tone="warning" title="Verify your email first" action={<Button type="button" variant="secondary" onClick={() => void resend()}>Send the link again</Button>}>
            {resent ?? "We sent a verification link when you registered. Open it, then press Continue again."}
          </Alert>
        )}
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

function GoogleStep({ onManual }: { onManual: () => void }) {
  const { refresh } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState<"manual" | "google" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function finish(next: "manual" | "google") {
    setBusy(next); setNotice(null);
    try {
      if (next === "manual") { onManual(); setBusy(null); return; }  // the last step finishes the set-up
      await api("/tenant/complete-onboarding", { method: "POST" });
      if (next === "google") {
        try {
          const { auth_url } = await api<{ auth_url: string }>("/google/connect", { method: "POST" });
          window.location.href = auth_url;
          return;
        } catch (e) {
          if (e instanceof ApiError && e.code === "google_config_pending") {
            await refresh();
            router.replace("/gbp/locations");
            return;
          }
          throw e;
        }
      }
    } catch (e) { setNotice(errorMessage(e)); setBusy(null); }
  }

  return (
    <Card>
      <h1 className="text-2xl font-semibold">How do you want to collect reviews?</h1>
      <p className="mt-1 text-ink-500">You can switch any time. Your QR/NFC cards work either way.</p>
      {notice && <div className="mt-4"><Alert tone="error">{notice}</Alert></div>}
      <div className="mt-6 grid gap-3">
        <button disabled={!!busy} onClick={() => void finish("manual")} className="tap flex items-start gap-4 rounded-lg border border-ink-300 p-4 text-left transition-colors hover:border-brand-600 hover:bg-brand-50/40 disabled:opacity-60">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-ink-50 text-ink-700"><Pencil className="h-5 w-5" aria-hidden /></span>
          <span><span className="block font-semibold">Use my Google review link</span><span className="mt-0.5 block text-sm text-ink-500">Fastest. Cards, AI writing help and scan analytics work immediately.</span></span>
        </button>
        <button disabled={!!busy} onClick={() => void finish("google")} className="tap flex items-start gap-4 rounded-lg border border-ink-300 p-4 text-left transition-colors hover:border-brand-600 hover:bg-brand-50/40 disabled:opacity-60">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-lg bg-ink-50 text-ink-700"><Link2 className="h-5 w-5" aria-hidden /></span>
          <span><span className="block font-semibold">Connect my Google Business Profile</span><span className="mt-0.5 block text-sm text-ink-500">Also syncs reviews and lets you approve AI-drafted replies. Requires Google access approval for FlowQR.</span></span>
        </button>
      </div>
      <details className="mt-5 rounded-lg bg-ink-50 p-4 text-sm text-ink-700">
        <summary className="cursor-pointer font-semibold">What does connecting Google allow?</summary>
        <ul className="mt-2 list-disc space-y-1.5 pl-5">
          <li>FlowQR can <b>read</b> your Business Profile and your reviews.</li>
          <li>It can change your profile, publish a Google Post or photo, or post a reply <b>only after you (or a teammate you chose) approve that exact change</b>. Posts, photos and replies are never sent on their own.</li>
          <li>You choose which locations to connect, you can switch everything off with one button, and you can disconnect Google at any time (Google Account &gt; Security &gt; Third-party access also lists it).</li>
          <li>Signing in with Google is separate: it only proves who you are. It never gives access to a Business Profile.</li>
        </ul>
        <p className="mt-3"><b>No Google Business Profile yet?</b> Choose the first option. Your cards, AI writing help and scan analytics work without it; you can create a profile at business.google.com and connect it later.</p>
      </details>
      {busy && <p className="mt-4 text-center text-sm text-ink-500">Setting things up…</p>}
    </Card>
  );
}

interface Sub {
  status: string; active: boolean; plan_name: string | null; trial_days_left: number | null; current_period_end: string | null;
  promo: { plan_name: string; ends_at: string } | null;
  limits: { locations: number; review_generations: number; review_replies: number; staff: number };
}
interface Campaign { id: string }

/** Last step. Everything on it is read from the real account: the plan or trial the business is on, and whether it already has a review page. Nothing is pre-filled. */
function ReadyStep() {
  const { refresh } = useAuth();
  const router = useRouter();
  const sub = useFetch<Sub>("/billing/subscription");
  const locs = useFetch<Location[]>("/locations");
  const camps = useFetch<Campaign[]>("/review-growth/campaigns");
  const [busy, setBusy] = useState<"campaign" | "finish" | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const first = locs.data?.[0];
  const hasCampaign = (camps.data?.length ?? 0) > 0;
  const loading = sub.loading || locs.loading || camps.loading;

  async function makeCampaign() {
    if (!first) return;
    setBusy("campaign"); setNotice(null);
    try {
      await api("/review-growth/campaigns", { method: "POST", body: { name: `${first.name} reviews`, location_id: first.id } });
      camps.reload();
    } catch (e) { setNotice(errorMessage(e)); } finally { setBusy(null); }
  }
  async function finish() {
    setBusy("finish"); setNotice(null);
    try {
      await api("/tenant/complete-onboarding", { method: "POST" });
      await refresh();
      router.replace("/overview");
    } catch (e) { setNotice(errorMessage(e)); setBusy(null); }
  }

  const s = sub.data;
  const planLine = !s ? null
    : s.promo ? `Your free ${s.promo.plan_name} month runs to ${new Date(s.promo.ends_at).toLocaleDateString("en-IN", { dateStyle: "medium" })}. Nothing is charged when it ends.`
    : s.status === "trialing" && s.trial_days_left !== null ? `Your free trial has ${s.trial_days_left} day${s.trial_days_left === 1 ? "" : "s"} left. Nothing is charged automatically.`
    : s.active ? `You are on the ${s.plan_name ?? "current"} plan.` : "Your plan is not active. Choose one in Settings.";

  return (
    <Card>
      <h1 className="text-2xl font-semibold">You are nearly ready</h1>
      <p className="mt-1 text-ink-500">Here is where your account stands. You can change any of it later.</p>
      {notice && <div className="mt-4"><Alert tone="error">{notice}</Alert></div>}
      {loading ? <div className="mt-6 grid place-items-center py-6"><Spinner /></div> : (
        <div className="mt-6 space-y-4">
          <section aria-labelledby="ob-plan" className="rounded-lg border border-ink-200 p-4">
            <div className="flex items-center justify-between gap-3"><h2 id="ob-plan" className="font-semibold">Your plan</h2>{s && <Badge tone={s.active ? "green" : "amber"}>{s.promo ? "free month" : s.status}</Badge>}</div>
            {sub.error ? <p className="mt-2 text-sm text-neg">{sub.error}</p> : <>
              <p className="mt-1 text-sm text-ink-700">{planLine}</p>
              {s && <p className="mt-2 text-sm text-ink-500">Includes {s.limits.locations} location{s.limits.locations === 1 ? "" : "s"}, {s.limits.review_generations} review-writing helps and {s.limits.review_replies} AI replies a month.</p>}</>}
          </section>
          <section aria-labelledby="ob-camp" className="rounded-lg border border-ink-200 p-4">
            <div className="flex items-center justify-between gap-3"><h2 id="ob-camp" className="font-semibold">Your first review page</h2><Badge tone={hasCampaign ? "green" : "gray"}>{hasCampaign ? "created" : "not yet"}</Badge></div>
            <p className="mt-1 text-sm text-ink-700">{hasCampaign ? "Customers who scan your card or QR code land on it. Open Review campaigns to see the QR code and to print it." : first ? `This is the page customers see when they scan your card. We will make one for ${first.name}.` : "Add a location first."}</p>
            {!hasCampaign && first && <div className="mt-3"><Button variant="secondary" loading={busy === "campaign"} onClick={() => void makeCampaign()}><QrCode className="h-4 w-4" aria-hidden /> Create my review page</Button></div>}
            {!first?.review_url && <p className="mt-2 text-xs text-ink-500">Your Google review link is not set yet, so the page cannot send customers to Google. Add it under Locations after this step.</p>}
          </section>
          <Button size="lg" className="w-full" loading={busy === "finish"} onClick={() => void finish()}>Go to my dashboard</Button>
          <p className="text-center text-xs text-ink-500">Your dashboard keeps a getting-started checklist until the essentials are done.</p>
        </div>)}
    </Card>
  );
}
