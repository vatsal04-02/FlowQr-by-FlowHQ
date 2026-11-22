"use client";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { Panel, Status } from "@/components/ui/kit";
import { Modal } from "@/components/ui/Modal";
import { useToast } from "@/components/ui/Toast";
import { OPERATOR_FILTERS, stateCounts, stateLabel, stateTone, stepTone, stepWord, type Journey } from "@/lib/agency-journey";
import { api, errorMessage } from "@/lib/api";
import { fmtDate, timeAgo } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

interface OpList { states: string[]; counts: Record<string, number>; journeys: Journey[] }
/** Authorization statuses where running the steps again can change something (the server refuses the rest). */
const RETRYABLE = ["consented", "invited", "accepted", "verified", "needs_attention"];
const when = (iso: string | null | undefined) => (iso ? fmtDate(iso, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "–");

/**
 * FlowHQ operator screen: where every business stands in the agency onboarding. Read-only apart from "Check again". The server answers 404 to anyone who is not a listed operator, so for everyone
 * else this page shows nothing. It never receives a token, a review or any Google content.
 */
export function AgencyOperatorScreen() {
  const [state, setState] = useState("");
  const { data, error, loading, reload } = useFetch<OpList>("/agency-ops/journeys", { state });
  const [open, setOpen] = useState<string | null>(null);

  if (error && !data) return <><PageHeader title="Agency onboarding" /><Alert tone="info" title="Not available">This screen is for FlowHQ agency operators. If you should have access, ask the owner to add your address to the operator list.</Alert></>;
  return (
    <>
      <PageHeader title="Agency onboarding" subtitle="Where every business stands in connecting Google and FlowHQ's manager access. Everything here comes from FlowQR's own records, not from guesses." />
      <div className="mb-4 flex flex-wrap gap-2" role="group" aria-label="Filter by state">
        {OPERATOR_FILTERS.map(([v, l]) => (
          <button key={v} type="button" aria-pressed={state === v} onClick={() => setState(v)} className={`min-h-9 rounded-full px-3 text-[13px] font-medium ${state === v ? "bg-ink text-white" : "bg-surface-2 text-ink-700 hover:bg-ink-100"}`}>
            {l}{v && data?.counts[v] ? ` · ${data.counts[v]}` : ""}
          </button>
        ))}
      </div>
      {data && !state && stateCounts(data.counts).length > 0 && <p className="mb-3 text-[13px] text-ink-500">{stateCounts(data.counts).map((c) => `${c.n} ${stateLabel(c.state).toLowerCase()}`).join(" · ")}</p>}
      <Panel title="Businesses" meta={data ? `${data.journeys.length} shown` : undefined} flush>
        {loading && !data ? <Skeleton className="m-3 h-48" /> : !data || data.journeys.length === 0 ? <div className="p-3"><EmptyState title="Nothing to show">No business has started the agency onboarding{state ? ` in this state` : ""} yet.</EmptyState></div> : (
          <div className="overflow-x-auto"><table className="dt min-w-[1100px]">
            <thead><tr><th>Business</th><th>Location</th><th>State</th><th>Google (customer)</th><th>Invited</th><th>Accepted</th><th>Verified</th><th>Consent</th><th>Last sync</th><th>Issue</th><th /></tr></thead>
            <tbody>{data.journeys.map((j) => {
              const l = j.locations[0], a = l?.authorization;
              return (
                <tr key={j.connection_id}>
                  <td className="font-medium">{j.tenant_name ?? "Business"}</td>
                  <td className="max-w-[180px] truncate">{l?.title ?? "–"}{j.locations.length > 1 ? ` +${j.locations.length - 1}` : ""}</td>
                  <td><Status tone={stateTone(j.state)}>{stateLabel(j.state)}</Status></td>
                  <td><Status tone={j.google.status === "active" ? "ok" : j.google.status === "revoked" ? "bad" : "idle"}>{j.google.status.replace("_", " ")}</Status></td>
                  <td>{when(a?.invite_sent_at)}</td><td>{when(a?.accepted_at)}</td><td>{when(a?.verified_at)}</td>
                  <td className="text-[12px]">{a ? <>{when(a.consented_at)}<br /><span className="text-ink-500">{a.consent_actions_recorded ? `${a.consent_actions.length} of 4 kinds` : "earlier wording"}</span></> : "–"}</td>
                  <td>{l?.sync.last_synced_at ? timeAgo(l.sync.last_synced_at) : "–"}{l && l.sync.consecutive_failures > 0 && <span className="block text-[12px] text-red-700">{l.sync.consecutive_failures} failing</span>}</td>
                  <td className="max-w-[200px] text-[12px]">{a?.failure_code ? <span className="text-amber-700">{a.failure_code}</span> : j.blocked ? <span className="text-amber-700">{j.blocked.code}</span> : "–"}{a?.lost_at || a?.removal_requested_at ? <span className="block text-ink-500">revoked</span> : null}</td>
                  <td><Button size="sm" variant="secondary" onClick={() => setOpen(j.connection_id)}>Open</Button></td>
                </tr>
              );
            })}</tbody>
          </table></div>
        )}
      </Panel>
      {open && <Detail id={open} onClose={() => setOpen(null)} onChanged={() => void reload()} />}
    </>
  );
}

function Detail({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const toast = useToast();
  const { data, error, loading, setData } = useFetch<Journey>(`/agency-ops/journeys/${id}`);
  const [busy, setBusy] = useState(false);
  async function again() {
    setBusy(true);
    try { setData(await api<Journey>(`/agency-ops/journeys/${id}/advance`, { method: "POST" })); toast("Checked again."); onChanged(); } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); }
  }
  const retryable = !!data?.locations.some((l) => l.authorization && RETRYABLE.includes(l.authorization.status));
  return (
    <Modal open onClose={onClose} title={data?.tenant_name ?? "Business"} footer={<><Button variant="secondary" onClick={onClose}>Close</Button><Button loading={busy} disabled={!retryable} title={retryable ? undefined : "Nothing to retry: the business has to start again"} onClick={() => void again()}>Check again</Button></>}>
      {loading && !data ? <Skeleton className="h-48" /> : error || !data ? <Alert tone="error">{error ?? "Not found"}</Alert> : (
        <div className="space-y-4 text-sm">
          <p><Status tone={stateTone(data.state)}>{stateLabel(data.state)}</Status> <span className="text-ink-600">{data.detail}</span></p>
          {data.blocked && <Alert tone="warning" title={`Blocked: ${data.blocked.code}`}>{data.blocked.message}</Alert>}
          <ol className="grid gap-1.5">{data.steps.map((s) => <li key={s.key} className="flex justify-between gap-3"><span>{s.label}</span><Status tone={stepTone(s.status)}>{stepWord(s.status)}</Status></li>)}</ol>
          {data.locations.map((l) => (
            <div key={l.google_location_id} className="rounded-xl border border-ink-100 p-3">
              <p className="font-semibold">{l.title ?? "Location"} <span className="font-normal text-ink-500">{l.authorization?.google_location_resource}</span></p>
              {l.authorization && (
                <dl className="mt-2 grid gap-1 text-[13px]">
                  {([["Authorization", l.authorization.status], ["Target", l.authorization.target_type], ["Consent", `${l.authorization.consent_version} · ${when(l.authorization.consented_at)} · ${l.authorization.consented_by_email ?? "–"}`],
                    ["Permissions agreed", l.authorization.consent_actions.join(", ") + (l.authorization.consent_actions_recorded ? "" : " (earlier wording)")], ["Failure code", l.authorization.failure_code ?? "–"],
                    ["Attempts", String(l.authorization.attempts ?? 0)], ["Next attempt", when(l.authorization.next_attempt_at)], ["Last asked Google", when(l.authorization.last_polled_at)], ["Notices sent", Object.keys(l.authorization.notices_sent ?? {}).join(", ") || (l.authorization.notice_sent_at ? "manager_added" : "–")],
                    ["Sync", `${l.sync.mode} · last ${when(l.sync.last_synced_at)} · ${l.sync.last_status ?? "never"} · ${l.sync.consecutive_failures} failing${l.sync.last_error ? ` · ${l.sync.last_error}` : ""}`]] as [string, string][]).map(([k, v]) => (
                    <div key={k} className="flex flex-wrap justify-between gap-2"><dt className="text-ink-500">{k}</dt><dd className="text-right font-medium">{v}</dd></div>))}
                </dl>
              )}
              <h4 className="mt-3 text-[13px] font-semibold">Mapping checks</h4>
              <ul className="mt-1 space-y-1 text-[13px]">{l.mapping.map((m) => <li key={m.name}><span aria-hidden className={m.ok ? "text-ok" : "text-red-600"}>{m.ok ? "✓" : "✗"}</span> <span className="sr-only">{m.ok ? "Passed" : "Failed"}: </span><b>{m.name}</b> <span className="text-ink-600">{m.detail}</span></li>)}</ul>
            </div>
          ))}
          <div><h4 className="text-[13px] font-semibold">Audit history</h4>
            <ul className="mt-1 space-y-1 text-[13px]">{data.timeline.map((t, i) => <li key={i}><span className="text-ink-500">{when(t.at)}</span> {t.event}{t.code ? <span className="text-ink-500"> ({t.code})</span> : null}</li>)}</ul></div>
        </div>
      )}
    </Modal>
  );
}
