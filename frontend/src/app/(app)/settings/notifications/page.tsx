"use client";
import { useState } from "react";
import { SettingsGroup } from "@/components/settings/parts";
import { Alert, ErrorState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Toggle } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useFetch } from "@/lib/use-api";

interface Prefs { email_new_review: boolean; email_flagged_review: boolean; email_sync_failed: boolean; email_trial_ending: boolean; email: string; verified: boolean }
type Key = Exclude<keyof Prefs, "email" | "verified">;

/** Grouped by how much it needs the owner: what needs you, the account, then routine activity (docs/DESIGN_SETTINGS_MOBILE.md, "Notifications" board). */
const GROUPS: { label: string; rows: [Key, string, string][] }[] = [
  { label: "Needs you", rows: [
    ["email_flagged_review", "A review needs you personally", "Medical, legal, threats or accusations. The AI won't reply until you've read it."],
    ["email_sync_failed", "Google sync stops", "Reviews from a location stop updating, usually because Google access was removed."],
  ] },
  { label: "Account", rows: [["email_trial_ending", "Your free trial is ending", "Once, when 5 days are left."]] },
  { label: "Activity", rows: [["email_new_review", "Every new review", "One email an hour at most, listing the reviews that came in."]] },
];

/**
 * Preferences › Notifications (PRD §5.4, §9): which events reach you by email, for this business. One email an hour at most, only about things that happened after you switched it on.
 * The bell in the top bar shows the same events without email. A switch saves the moment it is pressed and goes back if the server says no.
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
      <PageHeader title="Notifications" subtitle="Choose what FlowQR emails you about for this business. The bell in the app always shows everything." />
      {error && <ErrorState error={error} onRetry={() => void reload()} />}
      {loading && !data ? <Skeleton className="h-72" /> : data && (
        <div className="space-y-5">
          {!data.verified && <Alert tone="warning" title="Verify your email first">Emails only go to a verified address. Check your inbox for the verification link.</Alert>}
          {GROUPS.map((g, gi) => (
            <SettingsGroup key={g.label} id={`n-${gi}`} label={g.label}>
              {g.rows.map(([k, title, desc]) => (
                <div key={k} className="flex min-h-[76px] items-center gap-3 border-t border-set-line py-2.5 pl-4 pr-1 first:border-t-0">
                  <span className="min-w-0 flex-1"><span className="block text-[15px] font-bold leading-snug text-set-ink">{title}</span><span className="mt-0.5 block text-[13px] font-medium leading-snug text-set-muted">{desc}</span></span>
                  <Toggle on={data[k]} label={title} disabled={busy !== null} onChange={(v) => void set(k, v)} />
                </div>
              ))}
            </SettingsGroup>
          ))}
          <p className="px-1 text-[13px] font-medium text-set-muted">At most one email an hour, to {data.email}. Nothing is posted to Google from an email.</p>
        </div>
      )}
    </>
  );
}
