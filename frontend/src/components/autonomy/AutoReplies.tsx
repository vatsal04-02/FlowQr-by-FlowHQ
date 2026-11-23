"use client";
import { useEffect, useState } from "react";
import { Alert, Badge } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Form";
import { Panel, Toggle } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

interface AutoReply {
  enabled: boolean; running: boolean; not_running_because: string | null; min_rating: number; daily_limit: number; since: string; templates: string[]; using_built_in: boolean;
  built_in: Record<string, string[]>; placeholders: string[]; allowance: { cap: number; used: number; remaining: number }; limits: { min_chars: number; max_chars: number; max_templates: number };
  rules: string[]; recent: { id: string; rating: number; body: string; status: string; at: string; published_at: string | null; error: string | null }[];
}

interface ConsentInfo {
  wording_version: string; scopes: { scope: string; label: string; wording: string }[]; locations: { id: string; title: string | null }[];
  grants: { id: string; google_location_id: string; scope: string; active: boolean; granted_at: string }[];
}
const REPLY_SCOPE = "reply_template";

/** The owner's own agreement, per location, to automatic template replies. Without it nothing is ever sent, however the switch above is set; the wording shown is the wording the server records. */
function ReplyConsent({ onChanged }: { onChanged: () => void }) {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, reload } = useFetch<ConsentInfo>("/agent/consents");
  const [busy, setBusy] = useState<string | null>(null);
  if (error || !data) return null;
  const scope = data.scopes.find((x) => x.scope === REPLY_SCOPE);
  if (!scope || data.locations.length === 0) return null;
  const active = (loc: string) => data.grants.find((g) => g.google_location_id === loc && g.scope === REPLY_SCOPE && g.active);

  async function act(loc: string, grant: boolean, id?: string) {
    setBusy(loc);
    try {
      if (grant) await api("/agent/consents", { method: "POST", body: { location_id: loc, scope: REPLY_SCOPE, wording_version: data!.wording_version } });
      else await api(`/agent/consents/${id}/revoke`, { method: "POST", body: { reason: "Withdrawn by the owner" } });
      await reload(); onChanged(); toast(grant ? "Agreement recorded. Automatic replies can now run for this location." : "Withdrawn. Nothing is sent automatically for this location.");
    } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); }
  }

  return (
    <div className="rounded-xl bg-surface-2 p-4 text-sm">
      <p className="font-semibold">Your agreement for each location</p>
      <p className="mt-1 text-muted">{scope.wording}</p>
      <ul className="mt-3 space-y-2">
        {data.locations.map((l) => { const g = active(l.id); return (
          <li key={l.id} className="flex flex-wrap items-center justify-between gap-2">
            <span className="min-w-0"><span className="font-medium">{l.title ?? "Location"}</span> <Badge tone={g ? "green" : "amber"}>{g ? "You agreed" : "Not agreed yet"}</Badge>{g && <span className="ml-2 text-xs text-muted">{fmtDate(g.granted_at)}</span>}</span>
            {isAdmin && (g ? <Button variant="secondary" size="sm" loading={busy === l.id} onClick={() => void act(l.id, false, g.id)}>Withdraw</Button>
              : <Button size="sm" loading={busy === l.id} onClick={() => void act(l.id, true)}>I agree</Button>)}
          </li>); })}
      </ul>
      <p className="mt-2 text-xs text-muted">Only the business owner can agree or withdraw.</p>
    </div>
  );
}

/** AI › Autonomy › Automatic replies: the switch, the lowest rating, the reply templates, the plan allowance, and every reply that was sent without a person. Nothing is invented: the list is what was really sent. */
export function AutoReplies() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, reload } = useFetch<AutoReply>("/agent/auto-reply");
  const [templates, setTemplates] = useState<string[] | null>(null), [busy, setBusy] = useState(false);
  useEffect(() => { if (data) setTemplates(data.using_built_in ? [] : data.templates); }, [data]);

  async function save(body: Record<string, unknown>, ok: string) {
    setBusy(true);
    try { await api("/agent/auto-reply", { method: "PUT", body }); await reload(); toast(ok); } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); }
  }
  if (error) return <Alert tone="error">{error}</Alert>;
  if (!data || templates === null) return null;
  const a = data.allowance, dirty = JSON.stringify(templates) !== JSON.stringify(data.using_built_in ? [] : data.templates);
  const shown = templates.length ? templates : data.built_in.en;

  return (
    <Panel title="Automatic replies" meta="positive reviews, from your templates" action={<Badge tone={data.running ? "green" : "gray"}>{data.running ? "On" : "Off"}</Badge>}>
      <div className="space-y-5 px-5 pb-5 sm:px-6 sm:pb-6">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0"><p className="font-semibold">Reply to new 4 and 5 star reviews automatically</p>
            <p className="mt-0.5 text-sm text-muted">Sent from your templates, with the reviewer&rsquo;s first name and your business name. No AI writes these. Anything sensitive, low or mixed waits for you.</p>
            {!data.running && data.not_running_because && <p className="mt-1 text-sm text-warn">Not running: {data.not_running_because}.</p>}</div>
          <Toggle on={data.enabled} disabled={!isAdmin || busy} label="Automatic replies" onChange={(v) => void save({ enabled: v }, v ? "Automatic replies are on. Only reviews from now on are answered." : "Automatic replies are off.")} />
        </div>

        <ReplyConsent onChanged={() => void reload()} />

        <ul className="list-disc space-y-1 pl-5 text-sm text-muted">{data.rules.map((r) => <li key={r}>{r}</li>)}</ul>

        <dl className="grid gap-3 text-sm sm:grid-cols-3">
          <div><dt className="text-muted">This month</dt><dd className="num font-semibold">{a.used} of {a.cap} replies</dd><dd className="text-xs text-muted">shared with AI reply drafts; {a.remaining} left</dd></div>
          <div><dt className="text-muted">Lowest rating answered</dt>
            <dd><select aria-label="Lowest rating answered automatically" disabled={!isAdmin || busy} value={data.min_rating} onChange={(e) => void save({ min_rating: Number(e.target.value) }, "Saved.")} className="mt-0.5 min-h-10 rounded-xl border border-ink-200 bg-surface px-3 text-sm"><option value={4}>4 stars and up</option><option value={5}>5 stars only</option></select></dd></div>
          <div><dt className="text-muted">Automatic since</dt><dd className="font-semibold">{fmtDate(data.since)}</dd><dd className="text-xs text-muted">older reviews are never answered automatically</dd></div>
        </dl>

        <div>
          <p className="font-semibold">Your reply templates</p>
          <p className="mt-0.5 text-sm text-muted">{templates.length ? "Your own templates are used, in turn." : "The built-in templates are used (shown below). Add your own to replace them."} Use <code>{"{greeting}"}</code> for &ldquo;Dear Priya&rdquo; and <code>{"{business}"}</code> for your business name. No links, phone numbers, prices, offers or promises.</p>
          <div className="mt-3 space-y-2">
            {shown.map((t, i) => templates.length ? (
              <div key={i} className="flex gap-2"><Textarea label={`Template ${i + 1}`} rows={3} value={t} disabled={!isAdmin} wrapperClassName="flex-1" maxLength={data.limits.max_chars} onChange={(e) => setTemplates(templates.map((x, j) => (j === i ? e.target.value : x)))} />
                {isAdmin && <Button variant="secondary" size="sm" onClick={() => setTemplates(templates.filter((_, j) => j !== i))} aria-label={`Remove template ${i + 1}`}>Remove</Button>}</div>
            ) : <p key={i} className="rounded-xl bg-surface-2 p-3 text-sm text-ink-700">{t}</p>)}
          </div>
          {isAdmin && (
            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant="secondary" size="sm" disabled={templates.length >= data.limits.max_templates} onClick={() => setTemplates([...(templates.length ? templates : []), templates.length ? "" : data.built_in.en[0]])}>{templates.length ? "Add a template" : "Write my own"}</Button>
              {dirty && <Button size="sm" loading={busy} onClick={() => void save({ templates: templates.map((t) => t.trim()).filter(Boolean) }, templates.some((t) => t.trim()) ? "Templates saved." : "Using the built-in templates.")}>Save templates</Button>}
              {!data.using_built_in && <Button variant="secondary" size="sm" loading={busy} onClick={() => void save({ templates: [] }, "Using the built-in templates.")}>Use the built-in set</Button>}
            </div>)}
        </div>

        <div>
          <p className="font-semibold">Sent automatically</p>
          {data.recent.length === 0 ? <p className="mt-1 text-sm text-muted">Nothing yet. New positive reviews are answered within about five minutes of being synced.</p> : (
            <ul className="mt-2 divide-y divide-line text-sm">{data.recent.map((r) => (
              <li key={r.id} className="py-2.5"><div className="flex flex-wrap items-center gap-2"><span className="num">{r.rating}★</span><Badge tone={r.status === "published" ? "green" : r.status === "failed" ? "red" : "amber"}>{r.status}</Badge><span className="text-muted">{fmtDate(r.published_at ?? r.at)}</span></div>
                <p className="mt-1 text-ink-700">{r.body}</p>{r.error && <p className="text-xs text-neg">{r.error}</p>}</li>))}</ul>)}
        </div>
      </div>
    </Panel>
  );
}
