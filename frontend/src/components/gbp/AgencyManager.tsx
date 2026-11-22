"use client";
import clsx from "clsx";
import { Check, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert } from "@/components/ui/Card";
import { Panel, Status } from "@/components/ui/kit";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import {
  actionLabel, dateLine, defaultRoute, HOW_IT_WORKS, newRequestId, parseConsent, POLICY_FOOTNOTE, routeChoices, stateTone, stepIndex, STEPS, visibleActions,
  type AgencyView, type Route,
} from "@/lib/agency-ui";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-api";

interface Loc {
  google_location_id: string; title: string | null; status: string; message: string; state: string; headline: string; detail: string;
  accepted_at: string | null; removal_deadline_at: string | null;
}
interface View extends AgencyView { connection_id: string; auth_mode: "client_token" | "agency_account"; connection_status: string; locations: Loc[] }
interface AStatus { enabled: boolean; consent_version: string; consent_text: string; connections: View[] }

const fmt = (iso: string) => new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });

/**
 * The guided agency onboarding (docs/audits/GOOGLE_CLIENT_ACCOUNT_OPTIONS.md, section 12): choose a route, understand what you are approving, approve it, then watch it move through the
 * six states with the buttons that make sense. It renders NOTHING unless the server has the feature switched on (the status route answers 404 otherwise), so with the switch off the page is
 * exactly what it was. No token is ever sent to this component.
 */
export function AgencyManager({ available = false }: { available?: boolean }) {
  const { isAdmin } = useAuth();
  const toast = useToast();
  // `available` comes from /google/status (agency_available): when the path is not open for this business the route answers 404 by design, so it is not requested at all (a request known to
  // fail would be logged as an error in every customer's browser on every visit to the Locations screen).
  const { data, reload } = useFetch<AStatus>(available ? "/google/agency/status" : null);
  const [busy, setBusy] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [stopFor, setStopFor] = useState<string | null>(null);
  const [after, setAfter] = useState<View | null>(null); // the answer to a stop: the connection leaves the status list at once, the answer stays

  if (!data) return null;
  const views = data.connections.filter((v) => v.connection_status === "active" || v.locations.length > 0);
  if (!views.length && !after) return null;
  const consent = parseConsent(data.consent_text);

  async function approve(id: string, scope: Route, requestId: string): Promise<boolean> {
    setBusy(id); setProblem(null);
    try {
      await api("/google/agency/consent", { method: "POST", body: { connection_id: id, agree: true, consent_version: data!.consent_version, scope, request_id: requestId } });
      toast("Approved. We're sending the invitation and will keep this page up to date."); void reload(); return true;
    } catch (e) { setProblem(errorMessage(e)); return false; } finally { setBusy(null); }
  }
  async function again(id: string) {
    setBusy(id); setProblem(null);
    try { await api(`/google/agency/connections/${id}/advance`, { method: "POST" }); void reload(); } catch (e) { setProblem(errorMessage(e)); } finally { setBusy(null); }
  }
  async function reconnect() {
    setProblem(null);
    try { const { auth_url } = await api<{ auth_url: string }>("/google/connect", { method: "POST" }); window.location.href = auth_url; } catch (e) { setProblem(errorMessage(e)); }
  }
  async function stop() {
    const id = stopFor; if (!id) return;
    setBusy(id); setProblem(null);
    try { const v = await api<View>(`/google/agency/connections/${id}/stop`, { method: "POST", body: { confirm: true } }); setAfter(v); setStopFor(null); toast("FlowQR has stopped working on your profile."); void reload(); }
    catch (e) { setProblem(errorMessage(e)); } finally { setBusy(null); }
  }

  return (
    <section aria-label="FlowQR as your Manager" className="mt-4 space-y-4">
      {problem && <Alert tone="error" title="That did not work">{problem}</Alert>}
      {after && (
        <Panel title="FlowQR has stopped">
          {after.locations.map((l) => <p key={l.google_location_id} className="text-sm text-ink-700">{l.title ?? "Location"}: {l.message}. {dateLine(l, fmt) ?? ""}</p>)}
          <p className="mt-2 text-[13px] text-ink-500">If you want to check, open Google Business Profile, People and access.</p>
        </Panel>
      )}
      {views.map((v) => (
        <Guided key={v.connection_id} v={v} consent={consent} isAdmin={isAdmin} busy={busy === v.connection_id}
          onApprove={approve} onAgain={() => void again(v.connection_id)} onReconnect={() => void reconnect()} onAskStop={() => setStopFor(v.connection_id)} />
      ))}
      <Modal open={!!stopFor} onClose={() => setStopFor(null)} title="Stop FlowQR managing your profile?"
        footer={<><Button variant="secondary" onClick={() => setStopFor(null)}>Keep it</Button><Button variant="danger" loading={!!busy} onClick={() => void stop()}>Stop now</Button></>}>
        <p className="text-ink-700">FlowQR stops all work on your profile straight away: no syncing, replies, posts or changes. It then removes itself as a Manager in Google, and we record when. Reviews already in FlowQR stay in your inbox until you delete them.</p>
      </Modal>
    </section>
  );
}

function Guided({ v, consent, isAdmin, busy, onApprove, onAgain, onReconnect, onAskStop }: {
  v: View; consent: ReturnType<typeof parseConsent>; isAdmin: boolean; busy: boolean;
  onApprove: (id: string, scope: Route, requestId: string) => Promise<boolean>; onAgain: () => void; onReconnect: () => void; onAskStop: () => void;
}) {
  const [agree, setAgree] = useState(false);
  const [picked, setPicked] = useState<Route | null>(null);
  const [requestId, setRequestId] = useState(newRequestId);
  const [restarting, setRestarting] = useState(false);
  const choices = routeChoices(v.routes);
  const route = picked && v.routes.available.includes(picked) ? picked : defaultRoute(v.routes);
  const step = stepIndex(v.state, v.routes.selected > 0);
  const actions = visibleActions(v);
  const showForm = (v.locations.length === 0 && v.auth_mode === "client_token") || restarting;

  async function submit() {
    if (!route) return;
    if (await onApprove(v.connection_id, route, requestId)) { setRestarting(false); setAgree(false); setRequestId(newRequestId()); }
  }

  return (
    <Panel title="Let FlowQR help manage your profile" action={<ShieldCheck className="h-5 w-5 text-ink-400" aria-hidden />}>
      <ol aria-label="Progress" className="mb-5 grid grid-cols-4 gap-2">
        {STEPS.map((label, i) => (
          <li key={label} aria-current={i === step ? "step" : undefined} className="min-w-0 text-center">
            <span className={clsx("mx-auto grid h-7 w-7 place-items-center rounded-full text-xs font-semibold", i < step ? "bg-ok text-white" : i === step ? "border-2 border-ink-700 text-ink" : "bg-ink-100 text-ink-500")}>
              {i < step ? <Check className="h-4 w-4" aria-hidden /> : i + 1}
            </span>
            <span className={clsx("mt-1 block text-[12px] leading-4", i === step ? "font-semibold text-ink" : "text-ink-500")}>{label}</span>
          </li>
        ))}
      </ol>

      <details className="rounded-xl border border-ink-100 bg-ink-50/60 p-3 text-sm" open={showForm}>
        <summary className="cursor-pointer text-[13px] font-semibold">How this works, and what you are approving</summary>
        <ul className="mt-3 list-disc space-y-1.5 pl-5 text-ink-700">{HOW_IT_WORKS.map((t) => <li key={t}>{t}</li>)}</ul>
      </details>

      {showForm ? (
        <div className="mt-4 space-y-4">
          <fieldset>
            <legend className="text-sm font-semibold">Choose how to invite FlowQR</legend>
            <div role="radiogroup" aria-label="Invitation route" className="mt-2 grid gap-2 sm:grid-cols-2">
              {choices.map((c) => (
                <label key={c.id} className={clsx("flex min-h-11 cursor-pointer gap-3 rounded-xl border p-3 text-sm", route === c.id ? "border-ink-700" : "border-ink-100", !c.enabled && "cursor-not-allowed opacity-60")}>
                  <input type="radio" name={`route-${v.connection_id}`} className="mt-0.5 h-[18px] w-[18px]" disabled={!c.enabled || !isAdmin} checked={route === c.id} onChange={() => setPicked(c.id)} />
                  <span><span className="block font-semibold">{c.title}</span><span className="block text-ink-600">{c.body}</span>{!c.enabled && c.why && <span className="mt-1 block text-[12px] text-ink-500">{c.why}</span>}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <div>
            <p className="text-sm text-ink-700">{consent.lead}</p>
            <ul className="mt-2 list-disc space-y-1.5 pl-5 text-sm text-ink-700">{consent.bullets.map((b) => <li key={b}>{b}</li>)}</ul>
          </div>
          {isAdmin ? (
            <div className="space-y-3">
              <label className="flex min-h-11 cursor-pointer items-start gap-3 text-sm"><input type="checkbox" className="mt-0.5 h-[18px] w-[18px]" checked={agree} onChange={(e) => setAgree(e.target.checked)} /><span>I have read this and I approve FlowQR joining my profile as a Manager. I understand I can stop it at any time.</span></label>
              <Button size="sm" disabled={!agree || !route} loading={busy} onClick={() => void submit()}>Approve and invite FlowQR</Button>
              {busy && <p className="text-[13px] text-ink-500">This takes a few seconds.</p>}
            </div>
          ) : <p className="text-[13px] text-ink-500">Only an owner or admin can do this.</p>}
        </div>
      ) : (
        <div className="mt-4" aria-live="polite">
          <Status tone={stateTone(v.state)}>{v.headline}</Status>
          <p className="mt-1 text-sm text-ink-700">{v.detail}</p>
          {v.locations.length > 1 && (
            <ul className="mt-3 divide-y divide-ink-100 border-t border-ink-100">
              {v.locations.map((l) => (
                <li key={l.google_location_id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span className="truncate text-sm font-semibold">{l.title ?? "Location"}</span>
                  <Status tone={stateTone(l.state)}>{l.headline}</Status>
                </li>
              ))}
            </ul>
          )}
          {v.locations.length === 1 && dateLine(v.locations[0], fmt) && <p className="mt-1 text-xs text-ink-500">{dateLine(v.locations[0], fmt)}</p>}
          {isAdmin && actions.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {actions.map((a) => a === "start" ? null : (
                <Button key={a} size="sm" variant={a === "disconnect" ? "danger" : "secondary"} loading={a === "retry" && busy}
                  onClick={a === "retry" ? onAgain : a === "reconnect" ? onReconnect : a === "restart" ? () => setRestarting(true) : onAskStop}>{actionLabel(a)}</Button>
              ))}
            </div>
          )}
        </div>
      )}
      <p className="mt-4 text-[12px] text-ink-500">{v.policy_note || POLICY_FOOTNOTE}</p>
    </Panel>
  );
}
