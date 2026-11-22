"use client";
import clsx from "clsx";
import { Check, CircleDashed, Clock, Link2, Loader2, MapPin, OctagonAlert, ShieldCheck, X } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Skeleton } from "@/components/ui/Card";
import { Panel, Status } from "@/components/ui/kit";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { newRequestId, parseConsent } from "@/lib/agency-ui";
import {
  actionsToSend, canApprove, initialActions, pollDelay, progressSummary, stateLabel, stateTone, stepTone, stepWord, toggleAction, visibleActions, WHAT_HAPPENS_NEXT,
  type ActionCategory, type AvailableLocation, type Journey, type JourneyResponse, type JourneyStep, type StartView,
} from "@/lib/agency-journey";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate, timeAgo } from "@/lib/format";
import type { Location } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { OAUTH_ERRORS } from "./GoogleConnection";

const when = (iso: string | null | undefined) => (iso ? fmtDate(iso, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : null);

/**
 * The guided Google connection (docs/AGENCY_SELF_SERVICE_ONBOARDING_ARCHITECTURE.md): sign in with Google, choose the business location, approve FlowQR as your Manager, watch the
 * invitation, FlowHQ's acceptance and the access check happen, and see the synchronization status. Every line it shows is read from what the server derived from its own records; a stage is
 * shown as done only when the server says so. No token is ever sent to this page.
 */
export function AgencyJourneyScreen() { return <Suspense><Inner /></Suspense>; }

function Inner() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const sp = useSearchParams();
  const { data, error, loading, reload } = useFetch<JourneyResponse>("/google/agency/journey");
  const [problem, setProblem] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [stopFor, setStopFor] = useState<Journey | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const seenAt = useRef<number>(Date.now());
  const err = sp.get("error");

  useEffect(() => { if (sp.get("connected")) toast("Google account connected. Now choose your business location."); }, [sp, toast]);

  // Keep looking while FlowQR or Google is working on it: quickly at first, then slower, and not at all once nothing is waiting.
  const working = data?.journeys.find((j) => pollDelay(j.state, 0) !== null);
  useEffect(() => {
    if (!working) { seenAt.current = Date.now(); return; }
    const t = setTimeout(() => void reload(), pollDelay(working.state, Date.now() - seenAt.current) ?? 60_000);
    return () => clearTimeout(t);
  }, [working, data, reload]);

  async function connect() {
    setConnecting(true); setProblem(null);
    try { const { auth_url } = await api<{ auth_url: string }>("/google/connect", { method: "POST", params: { return_to: "journey" } }); window.location.href = auth_url; }
    catch (e) { setProblem(e instanceof ApiError && e.code === "google_config_pending" ? e.message : errorMessage(e)); setConnecting(false); }
  }
  async function checkAgain(id: string) {
    setBusy(id); setProblem(null);
    try { await api(`/google/agency/connections/${id}/advance`, { method: "POST" }); await reload(); } catch (e) { setProblem(errorMessage(e)); } finally { setBusy(null); }
  }
  async function stop() {
    if (!stopFor) return;
    setBusy(stopFor.connection_id); setProblem(null);
    try {
      const hasAuth = stopFor.locations.some((l) => l.authorization);
      if (hasAuth) await api(`/google/agency/connections/${stopFor.connection_id}/stop`, { method: "POST", body: { confirm: true } });
      else await api(`/google/connections/${stopFor.connection_id}`, { method: "DELETE" });
      toast("FlowQR has stopped working on your profile."); setStopFor(null); await reload();
    } catch (e) { setProblem(errorMessage(e)); } finally { setBusy(null); }
  }

  if (loading && !data) return <Skeleton className="h-64" />;
  if (error || !data) return <Alert tone="info" title="Guided connection is not available yet">FlowQR has not switched this on for your account. Your Google connection and everything else keep working as before.</Alert>;
  const canAct = isAdmin && data.can_act;

  return (
    <div className="space-y-4">
      {err && <Alert tone="error" title="Couldn't connect Google">{OAUTH_ERRORS[err] ?? "Something went wrong."}</Alert>}
      {problem && <Alert tone="error" title="That did not work">{problem}</Alert>}
      {data.journeys.length === 0 && data.start && <Start v={data.start} canAct={canAct} connecting={connecting} onConnect={() => void connect()} />}
      {data.journeys.map((j) => (
        <JourneyCard key={j.connection_id} j={j} data={data} canAct={canAct} busy={busy === j.connection_id} connecting={connecting}
          onConnect={() => void connect()} onCheck={() => void checkAgain(j.connection_id)} onStop={() => setStopFor(j)} onChanged={() => void reload()} />
      ))}
      <Modal open={!!stopFor} onClose={() => setStopFor(null)} title="Stop FlowQR managing your profile?"
        footer={<><Button variant="secondary" onClick={() => setStopFor(null)}>Keep it</Button><Button variant="danger" loading={!!busy} onClick={() => void stop()}>Stop now</Button></>}>
        <div className="space-y-2 text-ink-700">
          <p>FlowQR stops all work on your profile straight away: no syncing, replies, posts or changes.</p>
          <p>It then removes itself as a Manager in Google within {data.removal_business_days} business days, revokes your Google sign-in, and e-mails you to confirm. You stay the owner of your profile throughout, and you can also remove FlowQR yourself in Google (Business Profile, People and access).</p>
          <p>Reviews already in FlowQR stay in your inbox until you delete them.</p>
        </div>
      </Modal>
    </div>
  );
}

// ------------------------------------------------------------------ before there is a connection
function Start({ v, canAct, connecting, onConnect }: { v: StartView; canAct: boolean; connecting: boolean; onConnect: () => void }) {
  return (
    <Panel title="Connect your Google Business Profile" action={<ShieldCheck className="h-5 w-5 text-ink-400" aria-hidden />}>
      <Stages steps={v.steps} />
      {v.blocked ? <Alert tone="warning" title="On hold">{v.blocked.message}</Alert> : (
        <div className="mt-4">
          <p className="text-sm text-ink-700">{v.detail}</p>
          <p className="mt-2 text-[13px] text-ink-500">You sign in with your own Google account and approve Google&rsquo;s own consent screen. FlowQR never sees your Google password.</p>
          {canAct ? <Button className="mt-3" size="sm" icon={<Link2 className="h-4 w-4" />} loading={connecting} onClick={onConnect}>Connect Google</Button> : <p className="mt-3 text-[13px] text-ink-500">Only an owner or admin can connect Google.</p>}
        </div>
      )}
    </Panel>
  );
}

// ------------------------------------------------------------------ one connection
function JourneyCard({ j, data, canAct, busy, connecting, onConnect, onCheck, onStop, onChanged }: {
  j: Journey; data: JourneyResponse; canAct: boolean; busy: boolean; connecting: boolean; onConnect: () => void; onCheck: () => void; onStop: () => void; onChanged: () => void;
}) {
  const actions = visibleActions(j.actions, canAct);
  const sel = j.locations[0];
  const sum = progressSummary(j.steps);
  return (
    <>
      <Panel title="Connect Google and let FlowQR manage your profile" meta={j.google.email ?? undefined}
        action={<Status tone={stateTone(j.state)}>{stateLabel(j.state)}</Status>}>
        <p className="text-[13px] text-ink-500" aria-live="polite">{sum.done} of {sum.total} steps done{sum.next ? ` · next: ${sum.next.label}` : ""}</p>
        <Stages steps={j.steps} />
        <div className="mt-4" aria-live="polite">
          <p className="text-[17px] font-semibold">{j.headline}</p>
          <p className="mt-1 text-sm text-ink-700">{j.detail}</p>
          {WHAT_HAPPENS_NEXT[j.state] && <p className="mt-1 text-[13px] text-ink-500">{WHAT_HAPPENS_NEXT[j.state]}</p>}
        </div>
        {j.blocked && <div className="mt-3"><Alert tone="warning" title={j.state === "BLOCKED" ? "On hold: this is not an error" : "Note"}>{j.blocked.message}</Alert></div>}
        {(j.state === "FAILED" || j.state === "EXPIRED") && sel?.authorization && <div className="mt-3"><Alert tone={j.state === "EXPIRED" ? "warning" : "error"} title={j.state === "EXPIRED" ? "Expired" : "Could not finish"}>{j.detail} Nothing was changed on your profile.</Alert></div>}
        {actions.length > 0 && (
          <div className="mt-4 flex flex-wrap gap-2">
            {actions.map((a) => a === "connect" ? <Button key={a} size="sm" variant="secondary" icon={<Link2 className="h-4 w-4" />} loading={connecting} onClick={onConnect}>{j.google.status === "active" ? "Reconnect Google" : "Connect Google"}</Button>
              : a === "check_again" ? <Button key={a} size="sm" variant="secondary" loading={busy} onClick={onCheck}>Check again</Button>
              : a === "restart" ? <Button key={a} size="sm" variant="secondary" onClick={onConnect}>Start again</Button>
              : <Button key={a} size="sm" variant="danger" onClick={onStop}>Stop FlowQR managing my profile</Button>)}
          </div>
        )}
      </Panel>

      {j.actions.includes("select_location") && <LocationPicker j={j} canAct={canAct} onChanged={onChanged} onConnect={onConnect} />}
      {(j.actions.includes("approve") || (j.state === "CUSTOMER_CONSENT_PENDING")) && <ConsentPanel j={j} data={data} canAct={canAct} onChanged={onChanged} />}
      {sel && j.state !== "LOCATION_SELECTION_PENDING" && j.state !== "CUSTOMER_CONSENT_PENDING" && <Details j={j} data={data} />}
      <Account j={j} />
    </>
  );
}

function Stages({ steps }: { steps: JourneyStep[] }) {
  return (
    <ol aria-label="Progress" className="mt-4 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
      {steps.map((s, i) => (
        <li key={s.key} aria-current={s.status === "current" || s.status === "waiting" ? "step" : undefined}
          className={clsx("flex min-w-0 gap-2.5 rounded-xl border p-3", s.status === "done" ? "border-ink-100 bg-ink-50/40" : s.status === "blocked" || s.status === "failed" ? "border-amber-300 bg-amber-50/40" : s.status === "pending" ? "border-ink-100" : "border-ink-700")}>
          <span className={clsx("mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs font-semibold", s.status === "done" ? "bg-ok text-white" : s.status === "failed" ? "bg-red-600 text-white" : s.status === "blocked" ? "bg-amber-500 text-white" : s.status === "pending" ? "bg-ink-100 text-ink-500" : "border-2 border-ink-700 text-ink")}>
            {s.status === "done" ? <Check className="h-3.5 w-3.5" aria-hidden /> : s.status === "failed" ? <X className="h-3.5 w-3.5" aria-hidden /> : s.status === "blocked" ? <OctagonAlert className="h-3.5 w-3.5" aria-hidden />
              : s.status === "waiting" ? <Loader2 className="fq-spin h-3.5 w-3.5" aria-hidden /> : s.status === "current" ? <Clock className="h-3.5 w-3.5" aria-hidden /> : <span aria-hidden>{i + 1}</span>}
          </span>
          <span className="min-w-0">
            <span className="block text-[13px] font-semibold leading-4">{s.label}</span>
            <span className={clsx("block text-[12px]", s.status === "done" ? "text-ok" : stepTone(s.status) === "warn" ? "text-amber-700" : stepTone(s.status) === "bad" ? "text-red-700" : "text-ink-500")}>{stepWord(s.status)}</span>
            {s.message && s.status !== "done" && s.status !== "pending" && <span className="mt-1 block text-[12px] leading-4 text-ink-600">{s.message}</span>}
          </span>
        </li>
      ))}
    </ol>
  );
}

// ------------------------------------------------------------------ step: choose the location
function LocationPicker({ j, canAct, onChanged, onConnect }: { j: Journey; canAct: boolean; onChanged: () => void; onConnect: () => void }) {
  const toast = useToast();
  const mine = useFetch<Location[]>("/locations");
  const [pick, setPick] = useState<string | null>(null);
  const [map, setMap] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const avail = j.available_locations;
  const chosen: AvailableLocation | undefined = avail.find((a) => a.google_location_id === pick);
  const needsMap = !!chosen && !chosen.flowqr_location_id;

  async function save() {
    if (!chosen) return;
    setSaving(true); setProblem(null);
    try {
      const item = { google_location_id: chosen.google_location_id, selected: true, location_id: map && map !== "__new" ? map : null, create_location: map === "__new" };
      await api(`/google/connections/${j.connection_id}/selection`, { method: "PUT", body: { selections: [item] } });
      toast("Location chosen."); onChanged();
    } catch (e) { setProblem(errorMessage(e)); } finally { setSaving(false); }
  }

  return (
    <Panel title="Choose your business location" action={<MapPin className="h-5 w-5 text-ink-400" aria-hidden />}>
      {avail.length === 0 ? (
        <Alert tone="warning" title="No locations found" action={canAct ? <Button size="sm" onClick={onConnect}>Connect another Google account</Button> : undefined}>
          Google lists no Business Profile location for {j.google.email ?? "this account"}. Connect the Google account that owns or manages your listing.
        </Alert>
      ) : (
        <>
          <p className="text-sm text-ink-700">FlowQR will be invited to exactly the location you choose here, and to nothing else.</p>
          <div role="radiogroup" aria-label="Business location" className="mt-3 grid gap-2">
            {avail.map((a) => (
              <label key={a.google_location_id} className={clsx("flex min-h-11 cursor-pointer items-start gap-3 rounded-xl border p-3 text-sm", pick === a.google_location_id ? "border-ink-700" : "border-ink-100", a.taken && "cursor-not-allowed opacity-60")}>
                <input type="radio" name="gloc" className="mt-0.5 h-[18px] w-[18px]" disabled={!canAct || a.taken} checked={pick === a.google_location_id} onChange={() => { setPick(a.google_location_id); setMap(a.flowqr_location_id ?? ""); }} />
                <span className="min-w-0"><span className="block font-semibold">{a.title ?? "Location"}</span><span className="block truncate text-ink-600">{a.address}</span>
                  {a.taken && <span className="mt-1 block text-[12px] text-ink-500">This profile is already set up through FlowQR by another account. If it is yours, contact FlowQR support.</span>}</span>
              </label>
            ))}
          </div>
          {needsMap && (
            <label className="mt-3 block text-sm"><span className="font-medium">Which of your FlowQR locations is this?</span>
              <select value={map} onChange={(e) => setMap(e.target.value)} className="mt-1 block min-h-11 w-full max-w-sm rounded-lg border border-ink-300 bg-white px-2 text-sm sm:min-h-9">
                <option value="">Choose…</option>{mine.data?.filter((l) => l.is_active).map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}<option value="__new">+ Create it from the Google details</option>
              </select></label>
          )}
          {problem && <div className="mt-3"><Alert tone="error">{problem}</Alert></div>}
          {canAct ? <Button className="mt-3" size="sm" disabled={!chosen || (needsMap && !map)} loading={saving} onClick={() => void save()}>Use this location</Button> : <p className="mt-3 text-[13px] text-ink-500">Only an owner or admin can do this.</p>}
        </>
      )}
    </Panel>
  );
}

// ------------------------------------------------------------------ step: the customer's own agreement
function ConsentPanel({ j, data, canAct, onChanged }: { j: Journey; data: JourneyResponse; canAct: boolean; onChanged: () => void }) {
  const toast = useToast();
  const catalog: ActionCategory[] = data.consent.actions;
  const consent = parseConsent(data.consent.text);
  const [chosen, setChosen] = useState<string[]>(() => initialActions(catalog));
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [requestId, setRequestId] = useState(newRequestId);
  const targets = j.locations.filter((l) => l.selected);

  async function approve() {
    setBusy(true); setProblem(null);
    try {
      await api(`/google/agency/journey/start`, { method: "POST", body: { connection_id: j.connection_id, agree: true, consent_version: data.consent.version, actions: actionsToSend(chosen, catalog), request_id: requestId } });
      toast("Approved. We're sending the invitation and will keep this page up to date."); setRequestId(newRequestId()); onChanged();
    } catch (e) { setProblem(errorMessage(e)); } finally { setBusy(false); }
  }

  return (
    <Panel title="Approve FlowQR as your Manager" action={<ShieldCheck className="h-5 w-5 text-ink-400" aria-hidden />}>
      <p className="text-sm text-ink-700">Nothing is sent to Google until you approve. FlowQR will be invited to: <b>{targets.map((t) => t.title ?? "your location").join(", ") || "the location you chose"}</b>.</p>
      <div className="mt-3"><p className="text-sm text-ink-700">{consent.lead}</p>
        <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm text-ink-700">{consent.bullets.map((b) => <li key={b}>{b}</li>)}</ul></div>
      <fieldset className="mt-4">
        <legend className="text-sm font-semibold">What you allow FlowQR to do</legend>
        <p className="text-[13px] text-ink-500">Reading is needed for any of this. Each other kind of action is a separate choice, and FlowQR will be refused anything you leave unticked.</p>
        <div className="mt-2 grid gap-2">
          {catalog.map((c) => (
            <label key={c.id} className="flex min-h-11 cursor-pointer items-start gap-3 rounded-xl border border-ink-100 p-3 text-sm">
              <input type="checkbox" className="mt-0.5 h-[18px] w-[18px]" checked={chosen.includes(c.id)} disabled={c.required || !canAct} onChange={() => setChosen(toggleAction(chosen, c.id, catalog))} />
              <span><span className="block font-semibold">{c.label}{c.required && <span className="ml-2 text-[12px] font-normal text-ink-500">always included</span>}</span><span className="block text-ink-600">{c.description}</span></span>
            </label>
          ))}
        </div>
      </fieldset>
      <p className="mt-3 text-[13px] text-ink-500">Google will also e-mail you when FlowQR is added. FlowQR sends its own separate notice within {data.notice_hours} hours. To stop, press &ldquo;Stop FlowQR managing my profile&rdquo; here, or remove FlowQR in Google. It leaves within {data.removal_business_days} business days.</p>
      {canAct ? (
        <div className="mt-3 space-y-3">
          <label className="flex min-h-11 cursor-pointer items-start gap-3 text-sm"><input type="checkbox" className="mt-0.5 h-[18px] w-[18px]" checked={agreed} onChange={(e) => setAgreed(e.target.checked)} /><span>I have read this and I approve FlowQR joining my profile as a Manager for what I ticked above. I understand I can stop it at any time.</span></label>
          {problem && <Alert tone="error">{problem}</Alert>}
          <Button size="sm" disabled={!canApprove({ agreed, canAct, offered: j.actions, locations: targets.length })} loading={busy} onClick={() => void approve()}>Approve and invite FlowQR</Button>
        </div>
      ) : <p className="mt-3 text-[13px] text-ink-500">Only an owner or admin can approve this.</p>}
    </Panel>
  );
}

// ------------------------------------------------------------------ after approval: what happened, what is on record
function Details({ j, data }: { j: Journey; data: JourneyResponse }) {
  return (
    <>
      {j.locations.map((l) => (
        <Panel key={l.google_location_id} title={l.title ?? "Location"} meta={l.address ?? undefined}>
          <dl className="divide-y divide-ink-100 text-sm">
            {([
              ["Your approval", l.authorization ? `${when(l.authorization.consented_at)}${l.authorization.consent_actions_recorded ? "" : " (earlier wording: all four kinds of action, each still needing your approval)"}` : null],
              ["What you allowed", l.authorization ? l.authorization.consent_actions.map((id) => data.consent.actions.find((c) => c.id === id)?.label ?? id).join(", ") : null],
              ["Invitation sent to Google", when(l.authorization?.invite_sent_at)],
              ["Accepted by FlowHQ", when(l.authorization?.accepted_at)],
              ["Access verified", when(l.authorization?.verified_at)],
              ["Last access check", when(l.authorization?.last_verified_at)],
              ["Separate notice from FlowQR", l.authorization ? (l.authorization.notice_sent_at ? `E-mailed ${when(l.authorization.notice_sent_at)}` : l.authorization.accepted_at ? `Due by ${when(l.authorization.notice_due_at)}` : "Sent after FlowHQ accepts") : null],
              ["Review synchronization", syncLine(l.sync, j.operations_enabled, l.authorization?.status)],
              ["Last successful sync", l.sync.last_synced_at ? `${timeAgo(l.sync.last_synced_at)} (${when(l.sync.last_synced_at)})` : "Not yet"],
              ["Stopped / removed", l.authorization?.removal_requested_at ? `Requested ${when(l.authorization.removal_requested_at)}${l.authorization.removed_at ? `, FlowQR removed ${when(l.authorization.removed_at)}` : l.authorization.removal_deadline_at ? `, due by ${when(l.authorization.removal_deadline_at)}` : ""}` : l.authorization?.lost_at ? `FlowQR was removed in Google ${when(l.authorization.lost_at)}` : null],
            ] as [string, string | null][]).filter(([, v]) => v).map(([k, v]) => (
              <div key={k} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 py-2"><dt className="text-ink-500">{k}</dt><dd className="max-w-[28rem] text-right font-medium">{v}</dd></div>
            ))}
          </dl>
          {l.mapping.length > 0 && (
            <details className="mt-3 rounded-xl border border-ink-100 p-3 text-sm">
              <summary className="cursor-pointer text-[13px] font-semibold">How we checked this is your profile ({l.mapping.filter((m) => m.ok).length} of {l.mapping.length} checks passed)</summary>
              <ul className="mt-2 space-y-1.5">{l.mapping.map((m) => <li key={m.name} className="flex gap-2"><span aria-hidden className={m.ok ? "text-ok" : "text-red-600"}>{m.ok ? "✓" : "✗"}</span><span><span className="sr-only">{m.ok ? "Passed: " : "Failed: "}</span>{m.detail}</span></li>)}</ul>
            </details>
          )}
        </Panel>
      ))}
    </>
  );
}

function syncLine(s: { mode: string; last_status: string | null }, ops: boolean, authStatus?: string): string {
  if (s.mode === "agency") return s.last_status === "ok" ? "Running through FlowQR's Manager access" : s.last_status ? `Running through FlowQR's Manager access (last attempt: ${s.last_status.replace("_", " ")})` : "Queued: waiting for the first synchronization";
  if (authStatus === "verified" && !ops) return "Not switched on yet. Your reviews keep syncing through your own Google sign-in.";
  return "Running through your own Google sign-in";
}

function Account({ j }: { j: Journey }) {
  return (
    <details className="panel p-4 text-sm">
      <summary className="cursor-pointer text-[13px] font-semibold">Your Google connection and history</summary>
      <dl className="mt-3 divide-y divide-ink-100">
        {([["Google account", j.google.email], ["Connected", when(j.google.connected_at)], ["Locations found", String(j.google.locations_found)], ["Connection status", j.google.status.replace("_", " ")]] as [string, string | null][]).filter(([, v]) => v).map(([k, v]) => (
          <div key={k} className="flex items-baseline justify-between gap-4 py-2"><dt className="text-ink-500">{k}</dt><dd className="font-medium">{v}</dd></div>))}
      </dl>
      {j.timeline.length > 0 && (
        <>
          <h3 className="mt-4 flex items-center gap-1.5 text-[13px] font-semibold"><CircleDashed className="h-4 w-4 text-ink-400" aria-hidden />What happened, most recent first</h3>
          <ul className="mt-2 space-y-1.5 text-[13px] text-ink-700">{j.timeline.map((t, i) => <li key={i} className="flex flex-wrap gap-x-2"><span className="text-ink-500">{when(t.at)}</span><span>{t.event}</span></li>)}</ul>
        </>
      )}
    </details>
  );
}
