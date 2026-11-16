"use client";
import { YourDataPanel } from "@/components/YourDataPanel";
import { useState } from "react";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert, Badge, PageHeader } from "@/components/ui/Card";
import { ErrorSummary, Input, Select } from "@/components/ui/Form";
import { KV, Panel } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { CATEGORIES, fmtDate, LANGS, TIMEZONES } from "@/lib/format";
import { emailRule, phoneRule, required, useForm } from "@/lib/form";
import type { SubscriptionInfo } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

const SECTIONS = [["business", "Business profile"], ["data", "Your data"], ["plan", "Plan"]] as const;

export default function SettingsPage() {
  const { tenant, isAdmin, refresh } = useAuth();
  const toast = useToast();
  const sub = useFetch<SubscriptionInfo>("/billing/subscription");
  const [busy, setBusy] = useState(false);
  const f = useForm({
    name: tenant?.name ?? "", category: tenant?.category ?? CATEGORIES[0], email: tenant?.email ?? "", phone: tenant?.phone ?? "", address: tenant?.address ?? "", website: tenant?.website ?? "",
    language: tenant?.language ?? "en", timezone: tenant?.timezone ?? "Asia/Kolkata", logo_url: tenant?.logo_url ?? "",
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
      <PageHeader title="Business" subtitle="Your public details and your data. Your own profile and password are in Account; how AI writes is in AI › Brand voice." />
      {!isAdmin && <div className="mb-4"><Alert tone="info">Only owners and admins can change business settings.</Alert></div>}
      <div className="grid gap-6 lg:grid-cols-[180px_minmax(0,1fr)]">
        <nav aria-label="Settings sections" className="hidden lg:block"><ul className="sticky top-6 space-y-px text-sm">{SECTIONS.map(([id, l]) => <li key={id}><a href={`#${id}`} className="block rounded-full px-3 py-2 font-medium text-ink-700 hover:bg-surface">{l}</a></li>)}</ul></nav>
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
            {isAdmin && <div className="flex justify-end"><Button type="submit" loading={busy}>Save business settings</Button></div>}
          </form>

          <section id="data" className="scroll-mt-6"><YourDataPanel /></section>

          <section id="plan" className="scroll-mt-6"><Panel title="Plan" action={<LinkButton href="/settings/billing" size="sm" variant="secondary">Manage subscription</LinkButton>} flush>
            {sub.data && <div className="px-4 py-1"><KV rows={[
              ["Plan", <Badge key="p" tone="blue">{sub.data.plan_name ?? sub.data.plan ?? "None"}</Badge>], ["Status", sub.data.status.replace("_", " ")],
              ["AI generations / month", sub.data.limits.ai_generations.toLocaleString("en-IN")], ["Locations", `up to ${sub.data.limits.locations}`],
              ...(sub.data.status === "trialing" && sub.data.trial_ends_at ? [["Free trial ends", fmtDate(sub.data.trial_ends_at)] as [string, string]] : []),
            ]} /></div>}
          </Panel></section>
        </div>
      </div>
    </>
  );
}
