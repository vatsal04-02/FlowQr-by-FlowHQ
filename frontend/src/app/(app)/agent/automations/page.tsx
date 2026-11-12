"use client";
import { useState } from "react";
import { Alert, PageHeader, Skeleton } from "@/components/ui/Card";
import { Panel } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-api";

interface S { daily_plan: boolean; auto_draft_replies: boolean; auto_publish: boolean; notes: Record<string, string> }

function Toggle({ id, label, help, on, disabled, onChange }: { id: string; label: string; help: string; on: boolean; disabled?: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-start justify-between gap-4 py-3">
      <div className="min-w-0"><label htmlFor={id} className="text-sm font-semibold">{label}</label><p className="mt-0.5 text-[13px] text-ink-500">{help}</p></div>
      <input id={id} type="checkbox" role="switch" aria-checked={on} checked={on} disabled={disabled} onChange={(e) => onChange(e.target.checked)} className="mt-1 h-5 w-5 shrink-0" />
    </div>
  );
}

export default function Automations() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, setData } = useFetch<S>("/agent/settings");
  const [busy, setBusy] = useState(false);
  async function set(patch: Partial<S>) {
    setBusy(true);
    try { setData(await api<S>("/agent/settings", { method: "PUT", body: patch })); toast("Saved."); } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); }
  }
  return (
    <>
      <PageHeader eyebrow="AI Growth Agent" title="Automations" subtitle="What may happen without you clicking. Nothing ever goes live on Google, Meta or WhatsApp without an approval." />
      {error && <Alert tone="error">{error}</Alert>}
      {!isAdmin && <div className="mb-4"><Alert tone="info">Only owners and admins can change automations.</Alert></div>}
      {!data ? <Skeleton className="h-48" /> : (
        <div className="space-y-4">
          <Panel title="Preparation (safe)" meta="these only prepare work for you"><div className="divide-y divide-ink-100">
            <Toggle id="plan" label="Build a daily plan" on={data.daily_plan} disabled={!isAdmin || busy} onChange={(v) => void set({ daily_plan: v })} help="Once a day (after 6am your time) the agent refreshes what Google says and lists what needs attention. It changes nothing on Google." />
            <Toggle id="draft" label="Draft replies to new reviews" on={data.auto_draft_replies} disabled={!isAdmin || busy} onChange={(v) => void set({ auto_draft_replies: v })} help={data.notes.auto_draft_replies} />
          </div></Panel>
          <Panel title="Publishing" meta="not available">
            <Toggle id="pub" label="Publish automatically" on={false} disabled onChange={() => undefined} help={data.notes.auto_publish} />
          </Panel>
          <Panel title="What runs on its own">
            <ul className="ml-5 list-disc space-y-1 text-sm text-ink-700"><li>Every few minutes: due posts you approved are sent to Google at the time you chose.</li><li>Every 30 minutes: Google reviews are synced.</li><li>Every 15 minutes: replies you approved that failed for a temporary reason are retried (never ones you did not approve).</li><li>Daily: customer review-assistant text older than your retention period is deleted.</li></ul>
          </Panel>
        </div>)}
    </>
  );
}
