"use client";
import { useState } from "react";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert, Badge, Card, CardHeader, PageHeader } from "@/components/ui/Card";
import { ErrorSummary, Input, Select, Textarea } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { CATEGORIES, fmtDate, LANGS, TIMEZONES } from "@/lib/format";
import { emailRule, passwordRule, phoneRule, required, useForm } from "@/lib/form";
import type { SubscriptionInfo } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

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
      <PageHeader title="Business settings" subtitle="Your public details and how AI writes on your behalf." />
      {!isAdmin && <div className="mb-4"><Alert tone="info">Only owners and admins can change these settings.</Alert></div>}
      <form onSubmit={save} noValidate className="space-y-5">
        <ErrorSummary errors={f.errors} serverError={f.serverError} summaryRef={f.summaryRef} />
        <Card><CardHeader title="Business profile" subtitle="Shown on your customers' review page." />
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
        </Card>
        <Card><CardHeader title="AI reply style" subtitle="Guides every AI-drafted reply. You still approve each one." />
          <fieldset disabled={!isAdmin} className="space-y-4">
            <Input label="Brand tone" placeholder="e.g. warm, professional, reassuring" {...f.bind("brand_tone")} />
            <Textarea label="Instructions for replies" placeholder="e.g. Sign off as 'Team Geeta Krishna Physio'. For complaints, invite them to call 98765 43210. Never mention prices." hint="Don't include patient details or passwords." {...f.bind("ai_instructions")} />
          </fieldset>
        </Card>
        {isAdmin && <div className="flex justify-end"><Button type="submit" size="lg" loading={busy}>Save settings</Button></div>}
      </form>

      <Card className="mt-5"><CardHeader title="Plan" subtitle="Manage billing on the Subscription page." action={<LinkButton href="/subscription" size="sm" variant="secondary">Subscription</LinkButton>} />
        {sub.data && <dl className="grid gap-3 text-sm sm:grid-cols-4">
          {[["Plan", <Badge key="p" tone="orange">{sub.data.plan_name ?? sub.data.plan}</Badge>], ["Status", sub.data.status.replace("_", " ")], ["AI uses / month", sub.data.limits.ai_generations.toLocaleString("en-IN")], ["Locations", `up to ${sub.data.limits.locations}`]].map(([k, v]) => <div key={k as string} className="rounded-xl bg-ink-50 p-3"><dt className="text-ink-500">{k}</dt><dd className="mt-0.5 font-semibold">{v}</dd></div>)}
        </dl>}
        {sub.data?.status === "trialing" && sub.data.trial_ends_at && <p className="mt-3 text-xs text-ink-500">Free trial runs until {fmtDate(sub.data.trial_ends_at)}.</p>}
      </Card>
      <ProfileCard email={me?.user.email ?? ""} name={me?.user.full_name ?? ""} phone={me?.user.phone ?? ""} onSaved={refresh} />
    </>
  );
}

function ProfileCard({ email, name, phone, onSaved }: { email: string; name: string; phone: string; onSaved: () => Promise<unknown> }) {
  const toast = useToast();
  const p = useForm({ full_name: name, phone }, { full_name: required("Name"), phone: phoneRule });
  const pw = useForm({ current_password: "", new_password: "" }, { current_password: required("Current password"), new_password: passwordRule });
  const [b1, setB1] = useState(false), [b2, setB2] = useState(false);
  return (
    <div className="mt-5 grid gap-5 lg:grid-cols-2">
      <Card><CardHeader title="Your profile" subtitle={email} />
        <form noValidate className="space-y-4" onSubmit={async (e) => { e.preventDefault(); if (!p.validateAll()) return; setB1(true); try { await api("/auth/profile", { method: "PATCH", body: { full_name: p.values.full_name.trim(), phone: p.values.phone.trim() || null } }); await onSaved(); toast("Profile saved."); } catch (err) { p.fail(errorMessage(err)); } finally { setB1(false); } }}>
          <ErrorSummary errors={p.errors} serverError={p.serverError} summaryRef={p.summaryRef} />
          <Input label="Your name" {...p.bind("full_name")} /><Input label="Mobile" type="tel" {...p.bind("phone")} /><Button type="submit" loading={b1}>Save profile</Button>
        </form></Card>
      <Card><CardHeader title="Change password" subtitle="Other devices will be signed out." />
        <form noValidate className="space-y-4" onSubmit={async (e) => { e.preventDefault(); if (!pw.validateAll()) return; setB2(true); try { await api("/auth/change-password", { method: "POST", body: pw.values }); pw.setValues({ current_password: "", new_password: "" }); toast("Password changed."); } catch (err) { pw.fail(errorMessage(err)); } finally { setB2(false); } }}>
          <ErrorSummary errors={pw.errors} serverError={pw.serverError} summaryRef={pw.summaryRef} />
          <Input label="Current password" type="password" autoComplete="current-password" {...pw.bind("current_password")} />
          <Input label="New password" type="password" autoComplete="new-password" {...pw.bind("new_password")} /><Button type="submit" loading={b2}>Change password</Button>
        </form></Card>
    </div>
  );
}
