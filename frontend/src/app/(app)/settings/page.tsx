"use client";
import { useEffect, useState } from "react";
import { useGoogleError } from "@/components/GoogleAuth";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert, Badge, PageHeader } from "@/components/ui/Card";
import { ErrorSummary, Input, Select, Textarea } from "@/components/ui/Form";
import { KV, Panel } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { CATEGORIES, fmtDate, LANGS, TIMEZONES } from "@/lib/format";
import { emailRule, passwordRule, phoneRule, required, useForm } from "@/lib/form";
import type { SubscriptionInfo } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

const SECTIONS = [["business", "Business profile"], ["ai", "AI reply style"], ["plan", "Plan"], ["you", "Your profile"], ["signin", "Sign-in methods"], ["password", "Password"]] as const;

export default function SettingsPage() {
  const { tenant, me, isAdmin, refresh } = useAuth();
  const toast = useToast();
  const sub = useFetch<SubscriptionInfo>("/billing/subscription");
  const [busy, setBusy] = useState(false);
  const f = useForm({
    name: tenant?.name ?? "", category: tenant?.category ?? CATEGORIES[0], email: tenant?.email ?? "", phone: tenant?.phone ?? "", address: tenant?.address ?? "", website: tenant?.website ?? "",
    language: tenant?.language ?? "en", timezone: tenant?.timezone ?? "Asia/Kolkata", logo_url: tenant?.logo_url ?? "", brand_tone: tenant?.brand_tone ?? "", ai_instructions: tenant?.ai_instructions ?? "",
  }, { name: required("Business name"), email: (v) => (String(v).trim() ? emailRule(v) : undefined), phone: phoneRule,
    logo_url: (v) => (!String(v).trim() || String(v).startsWith("https://") ? undefined : "Logo link must start with https://") });

  async function save(e: React.FormEvent) {
    e.preventDefault(); f.setServerError(null);
    if (!f.validateAll()) return;
    setBusy(true);
    try {
      const body = Object.fromEntries(Object.entries(f.values).map(([k, v]) => [k, typeof v === "string" ? v.trim() || null : v]));
      body.name = f.values.name.trim(); body.language = f.values.language; body.timezone = f.values.timezone;
      await api("/tenant", { method: "PATCH", body }); await refresh(); toast("Settings saved.");
    } catch (err) { f.fail(errorMessage(err)); } finally { setBusy(false); }
  }

  return (
    <>
      <PageHeader eyebrow="Business" title="Settings" subtitle="Your public details, how AI writes on your behalf, and your account." />
      {!isAdmin && <div className="mb-4"><Alert tone="info">Only owners and admins can change business settings.</Alert></div>}
      <div className="grid gap-6 lg:grid-cols-[180px_minmax(0,1fr)]">
        <nav aria-label="Settings sections" className="hidden lg:block"><ul className="sticky top-6 space-y-px text-sm">{SECTIONS.map(([id, l]) => <li key={id}><a href={`#${id}`} className="block rounded-lg px-2.5 py-1.5 font-medium text-ink-700 hover:bg-ink-100/70">{l}</a></li>)}</ul></nav>
        <div className="min-w-0 space-y-4">
          <form onSubmit={save} noValidate className="space-y-4">
            <ErrorSummary errors={f.errors} serverError={f.serverError} summaryRef={f.summaryRef} />
            <section id="business" className="scroll-mt-6"><Panel title="Business profile" meta="shown on your customers' review page">
              <fieldset disabled={!isAdmin} className="space-y-4">
                <Input label="Business name" required {...f.bind("name")} />
                <div className="grid gap-4 sm:grid-cols-2">
                  <Select label="Category" {...f.bind("category")}>{[...new Set([f.values.category, ...CATEGORIES])].map((c) => <option key={c}>{c}</option>)}</Select>
                  <Input label="Website" inputMode="url" {...f.bind("website")} />
                  <Input label="Business email" type="email" {...f.bind("email")} /><Input label="Phone" type="tel" {...f.bind("phone")} />
                </div>
                <Input label="Address" {...f.bind("address")} />
                <Input label="Logo link" inputMode="url" placeholder="https://…/logo.png" hint="Shown on the QR landing page. Must be an https link to an image you own." {...f.bind("logo_url")} />
                <div className="grid gap-4 sm:grid-cols-2">
                  <Select label="Preferred language" {...f.bind("language")}>{LANGS.map((l) => <option key={l.v} value={l.v}>{l.l}</option>)}</Select>
                  <Select label="Time zone" {...f.bind("timezone")}>{TIMEZONES.map((t) => <option key={t}>{t}</option>)}</Select>
                </div>
              </fieldset>
            </Panel></section>
            <section id="ai" className="scroll-mt-6"><Panel title="AI reply style" meta="guides every AI-drafted reply; you still approve each one">
              <fieldset disabled={!isAdmin} className="space-y-4">
                <Input label="Brand tone" placeholder="e.g. warm, professional, reassuring" {...f.bind("brand_tone")} />
                <Textarea label="Instructions for replies" placeholder="e.g. Sign off as 'Team Demo Clinic'. For complaints, invite them to call the front desk. Never mention prices." hint="Don't include patient details or passwords." {...f.bind("ai_instructions")} />
              </fieldset>
            </Panel></section>
            {isAdmin && <div className="flex justify-end"><Button type="submit" loading={busy}>Save business settings</Button></div>}
          </form>

          <section id="plan" className="scroll-mt-6"><Panel title="Plan" action={<LinkButton href="/subscription" size="sm" variant="secondary">Manage subscription</LinkButton>} flush>
            {sub.data && <div className="px-4 py-1"><KV rows={[
              ["Plan", <Badge key="p" tone="blue">{sub.data.plan_name ?? sub.data.plan ?? "None"}</Badge>], ["Status", sub.data.status.replace("_", " ")],
              ["AI generations / month", sub.data.limits.ai_generations.toLocaleString("en-IN")], ["Locations", `up to ${sub.data.limits.locations}`],
              ...(sub.data.status === "trialing" && sub.data.trial_ends_at ? [["Free trial ends", fmtDate(sub.data.trial_ends_at)] as [string, string]] : []),
            ]} /></div>}
          </Panel></section>
          <ProfilePanels email={me?.user.email ?? ""} name={me?.user.full_name ?? ""} phone={me?.user.phone ?? ""}
            hasLocalLogin={me?.user.has_local_login ?? true} googleLinked={me?.user.google_linked ?? false} onSaved={refresh} />
        </div>
      </div>
    </>
  );
}

function ProfilePanels({ email, name, phone, hasLocalLogin, googleLinked, onSaved }: { email: string; name: string; phone: string; hasLocalLogin: boolean; googleLinked: boolean; onSaved: () => Promise<unknown> }) {
  const toast = useToast();
  const p = useForm({ full_name: name, phone }, { full_name: required("Name"), phone: phoneRule });
  const pw = useForm({ current_password: "", new_password: "" }, { current_password: required("Current password"), new_password: passwordRule });
  const first = useForm({ new_password: "" }, { new_password: passwordRule });
  const [b1, setB1] = useState(false), [b2, setB2] = useState(false), [b3, setB3] = useState(false), [b4, setB4] = useState(false);
  const googleError = useGoogleError();
  const [linkError, setLinkError] = useState<string | null>(null);
  useEffect(() => {
    if (new URLSearchParams(window.location.search).get("google") === "linked") {
      toast("Google account connected.");
      void onSaved();
      window.history.replaceState(null, "", window.location.pathname + window.location.hash);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  async function connectGoogle() {
    setB4(true); setLinkError(null);
    try {
      const { auth_url } = await api<{ auth_url: string }>("/auth/google/link", { method: "POST" });
      window.location.href = auth_url; // full redirect to Google
    } catch (err) { setLinkError(errorMessage(err)); setB4(false); }
  }

  return (
    <>
      <section id="signin" className="scroll-mt-6"><Panel title="Sign-in methods" meta="how you can log in to FlowQR">
        <div className="space-y-4">
          {(googleError || linkError) && <Alert tone="error" title="Google wasn't connected">{googleError ?? linkError}</Alert>}
          <KV rows={[
            ["Email and password", hasLocalLogin ? <Badge key="pw" tone="green">On</Badge> : <Badge key="pw">Not set</Badge>],
            ["Google", googleLinked ? <Badge key="g" tone="green">Connected</Badge> : <Badge key="g">Not connected</Badge>],
          ]} />
          {!googleLinked && <Button variant="secondary" loading={b4} onClick={() => void connectGoogle()}>Connect Google account</Button>}
          <p className="text-xs text-ink-500">This only lets you sign in with Google. It is separate from connecting your Google Business Profile for reviews.</p>
        </div></Panel></section>
      <section id="you" className="scroll-mt-6"><Panel title="Your profile" meta={email}>
        <form noValidate className="space-y-4" onSubmit={async (e) => { e.preventDefault(); if (!p.validateAll()) return; setB1(true); try { await api("/auth/profile", { method: "PATCH", body: { full_name: p.values.full_name.trim(), phone: p.values.phone.trim() || null } }); await onSaved(); toast("Profile saved."); } catch (err) { p.fail(errorMessage(err)); } finally { setB1(false); } }}>
          <ErrorSummary errors={p.errors} serverError={p.serverError} summaryRef={p.summaryRef} />
          <div className="grid gap-4 sm:grid-cols-2"><Input label="Your name" {...p.bind("full_name")} /><Input label="Mobile" type="tel" {...p.bind("phone")} /></div>
          <Button type="submit" loading={b1}>Save profile</Button>
        </form></Panel></section>
      {!hasLocalLogin ? (
        <section id="password" className="scroll-mt-6"><Panel title="Set a password" meta="optional: lets you also log in with your email; other devices will be signed out">
          <form noValidate className="space-y-4" onSubmit={async (e) => { e.preventDefault(); if (!first.validateAll()) return; setB3(true); try { await api("/auth/set-password", { method: "POST", body: first.values }); first.setValues({ new_password: "" }); await onSaved(); toast("Password set."); } catch (err) { first.fail(errorMessage(err)); } finally { setB3(false); } }}>
            <ErrorSummary errors={first.errors} serverError={first.serverError} summaryRef={first.summaryRef} />
            <Input label="New password" type="password" autoComplete="new-password" hint="At least 10 characters with upper and lower case letters." {...first.bind("new_password")} />
            <Button type="submit" loading={b3}>Set password</Button>
          </form></Panel></section>
      ) : (
      <section id="password" className="scroll-mt-6"><Panel title="Change password" meta="other devices will be signed out">
        <form noValidate className="space-y-4" onSubmit={async (e) => { e.preventDefault(); if (!pw.validateAll()) return; setB2(true); try { await api("/auth/change-password", { method: "POST", body: pw.values }); pw.setValues({ current_password: "", new_password: "" }); toast("Password changed."); } catch (err) { pw.fail(errorMessage(err)); } finally { setB2(false); } }}>
          <ErrorSummary errors={pw.errors} serverError={pw.serverError} summaryRef={pw.summaryRef} />
          <div className="grid gap-4 sm:grid-cols-2"><Input label="Current password" type="password" autoComplete="current-password" {...pw.bind("current_password")} /><Input label="New password" type="password" autoComplete="new-password" {...pw.bind("new_password")} /></div>
          <Button type="submit" loading={b2}>Change password</Button>
        </form></Panel></section>
      )}
    </>
  );
}
