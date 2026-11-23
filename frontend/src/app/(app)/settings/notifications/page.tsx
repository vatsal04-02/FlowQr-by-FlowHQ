"use client";
import { useState } from "react";
import { Alert, ErrorState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Panel, Toggle } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useFetch } from "@/lib/use-api";

interface Prefs { email_new_review: boolean; email_flagged_review: boolean; email_sync_failed: boolean; email_trial_ending: boolean; email: string; verified: boolean }
type Key = Exclude<keyof Prefs, "email" | "verified">;

const ROWS: [Key, string, string][] = [
  ["email_flagged_review", "A review needs you personally", "Medical, legal, threats or accusations: the AI won't reply until you have read it."],
  ["email_sync_failed", "Google sync stops", "Reviews from a location stop updating, usually because Google access was removed."],
  ["email_trial_ending", "Your free trial is ending", "Once, when 5 days are left."],
  ["email_new_review", "Every new review", "One email an hour at most, listing the reviews that came in."],
];

/**
 * Settings › Notifications (PRD §5.4, §9): which events reach you by email, for this business. One email an hour at most, only about
 * things that happened after you switched it on. The bell in the top bar shows the same events without email.
 */
export default function NotificationsPage() {
  const toast = useToast();
  const { data, error, loading, setData, reload } = useFetch<Prefs>("/notifications/preferences");
  const [busy, setBusy] = useState<Key | null>(null);

  async function set(k: Key, v: boolean) {
    if (!data) return;
    const next = { ...data, [k]: v };
    setBusy(k); setData(next);
    try {
      const { email_new_review, email_flagged_review, email_sync_failed, email_trial_ending } = next;
      setData(await api<Prefs>("/notifications/preferences", { method: "PUT", body: { email_new_review, email_flagged_review, email_sync_failed, email_trial_ending } }));
      toast(v ? "You'll get these emails." : "Those emails are off.");
    } catch (e) { setData(data); toast(errorMessage(e), "error"); } finally { setBusy(null); }
  }

  return (
    <>
      <PageHeader title="Notifications" subtitle="Choose what FlowQR emails you about for this business. The bell shows everything either way." />
      {error && <ErrorState error={error} onRetry={() => void reload()} />}
      {loading && !data ? <Skeleton className="h-72" /> : data && (
        <div className="max-w-3xl space-y-4">
          {!data.verified && <Alert tone="warning" title="Verify your email first">Emails only go to a verified address. Check your inbox for the verification link.</Alert>}
          <Panel title="Email me when" meta={`to ${data.email}`}>
            <ul className="divide-y divide-line">
              {ROWS.map(([k, title, desc]) => (
                <li key={k} className="flex items-center justify-between gap-4 py-3.5 first:pt-0 last:pb-0">
                  <span className="min-w-0"><span className="block font-semibold">{title}</span><span className="block text-[13px] text-muted">{desc}</span></span>
                  <Toggle on={data[k]} label={title} disabled={busy !== null} onChange={(v) => void set(k, v)} />
                </li>
              ))}
            </ul>
          </Panel>
          <p className="text-[13px] text-muted">At most one email an hour, only about things that happen after you switch a setting on. Nothing is posted to Google from an email.</p>
        </div>
      )}
    </>
  );
}
