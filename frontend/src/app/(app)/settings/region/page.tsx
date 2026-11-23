"use client";
import { useState } from "react";
import { StickyActionBar } from "@/components/settings/parts";
import { Button } from "@/components/ui/Button";
import { Alert, PageHeader } from "@/components/ui/Card";
import { ErrorSummary, Select } from "@/components/ui/Form";
import { Panel } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { LANGS, TIMEZONES } from "@/lib/format";
import { useForm } from "@/lib/form";

/** Preferences › Language and time zone. These two fields used to sit in the business profile; each setting now has one home. */
export default function RegionPage() {
  const { tenant, isAdmin, refresh } = useAuth();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const f = useForm({ language: tenant?.language ?? "en", timezone: tenant?.timezone ?? "Asia/Kolkata" }, {});

  async function save(e: React.FormEvent) {
    e.preventDefault(); f.setServerError(null); setBusy(true);
    try { await api("/tenant", { method: "PATCH", body: { language: f.values.language, timezone: f.values.timezone } }); await refresh(); toast("Saved."); }
    catch (err) { f.fail(errorMessage(err)); } finally { setBusy(false); }
  }
  return (
    <>
      <PageHeader title="Language and time zone" subtitle="Sets the language of your customers' review page and the time zone for dates, reports and scheduled posts." />
      {!isAdmin && <div className="mb-4"><Alert tone="info">Only owners and admins can change this.</Alert></div>}
      <form onSubmit={save} noValidate className="space-y-4">
        <ErrorSummary errors={f.errors} serverError={f.serverError} summaryRef={f.summaryRef} />
        <Panel>
          <fieldset disabled={!isAdmin} className="grid gap-4 sm:grid-cols-2">
            <Select label="Preferred language" {...f.bind("language")}>{LANGS.map((l) => <option key={l.v} value={l.v}>{l.l}</option>)}</Select>
            <Select label="Time zone" {...f.bind("timezone")}>{TIMEZONES.map((t) => <option key={t}>{t}</option>)}</Select>
          </fieldset>
        </Panel>
        {isAdmin && <StickyActionBar note="Nothing changes for your customers until you save."><Button type="submit" variant="brand" loading={busy} className="w-full md:w-auto">Save</Button></StickyActionBar>}
      </form>
    </>
  );
}
