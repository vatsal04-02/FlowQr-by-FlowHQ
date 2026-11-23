"use client";
import { useState } from "react";
import { StickyActionBar } from "@/components/settings/parts";
import { Button } from "@/components/ui/Button";
import { Alert, PageHeader } from "@/components/ui/Card";
import { ErrorSummary, Input, Select } from "@/components/ui/Form";
import { Panel } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { CATEGORIES } from "@/lib/format";
import { emailRule, phoneRule, required, useForm } from "@/lib/form";

/** Business › Business profile: what customers see. Language and time zone moved to Preferences; "Your data" to Security & activity; the plan to Billing. */
export default function BusinessProfilePage() {
  const { tenant, isAdmin, refresh } = useAuth();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const start = {
    name: tenant?.name ?? "", category: tenant?.category ?? CATEGORIES[0], email: tenant?.email ?? "", phone: tenant?.phone ?? "", address: tenant?.address ?? "", website: tenant?.website ?? "",
    logo_url: tenant?.logo_url ?? "",
  };
  const f = useForm(start, { name: required("Business name"), email: (v) => (String(v).trim() ? emailRule(v) : undefined), phone: phoneRule,
    logo_url: (v) => (!String(v).trim() || String(v).startsWith("https://") ? undefined : "Logo link must start with https://") });

  const discard = () => { f.setValues(start); f.setServerError(null); };

  async function save(e: React.FormEvent) {
    e.preventDefault(); f.setServerError(null);
    if (!f.validateAll()) return;
    setBusy(true);
    try {
      const body = Object.fromEntries(Object.entries(f.values).map(([k, v]) => [k, typeof v === "string" ? v.trim() || null : v]));
      body.name = f.values.name.trim();
      await api("/tenant", { method: "PATCH", body }); await refresh(); toast("Business profile saved.");
    } catch (err) { f.fail(errorMessage(err)); } finally { setBusy(false); }
  }

  return (
    <>
      <PageHeader title="Business profile" subtitle="Shown on your customers' review page. Language and time zone are under Preferences." />
      {!isAdmin && <div className="mb-4"><Alert tone="info">Only owners and admins can change business settings.</Alert></div>}
      <form onSubmit={save} noValidate className="space-y-4">
        <ErrorSummary errors={f.errors} serverError={f.serverError} summaryRef={f.summaryRef} />
        <Panel>
          <fieldset disabled={!isAdmin} className="space-y-4">
            <Input label="Business name" required {...f.bind("name")} />
            <div className="grid gap-4 [grid-template-columns:repeat(auto-fit,minmax(min(240px,100%),1fr))]">
              <Select label="Category" {...f.bind("category")}>{[...new Set([f.values.category, ...CATEGORIES])].map((c) => <option key={c}>{c}</option>)}</Select>
              <Input label="Website" inputMode="url" {...f.bind("website")} />
              <Input label="Business email" type="email" {...f.bind("email")} />
              <Input label="Phone" type="tel" {...f.bind("phone")} />
            </div>
            <Input label="Address" {...f.bind("address")} />
            <Input label="Logo link" inputMode="url" placeholder="https://…/logo.png" hint="Shown on the QR landing page. Must be an https link to an image you own." {...f.bind("logo_url")} />
          </fieldset>
        </Panel>
        {isAdmin && <StickyActionBar note="Your customers see these details on the review page."><Button type="button" variant="secondary" onClick={discard} className="w-full md:w-auto">Discard</Button><Button type="submit" variant="brand" loading={busy} className="w-full md:w-auto">Save changes</Button></StickyActionBar>}
      </form>
    </>
  );
}
