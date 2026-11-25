"use client";
import clsx from "clsx";
import { ArrowRight, CheckCircle2, CircleDashed, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { WaitingCard } from "@/components/autonomy/Actions";
import { Card, Title } from "@/components/seo/visuals";
import { Button } from "@/components/ui/Button";
import { Accordion } from "@/components/ui/Accordion";
import { Alert, Badge, Skeleton } from "@/components/ui/Card";
import { Input } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { STATUS_WORDS } from "@/lib/autonomy";
import { fmtNum, timeAgo } from "@/lib/format";
import { useLocationScope } from "@/lib/location-scope";
import { AREA_FOR_FIELD, areaStep, type AreaStep, type PrepareResponse } from "@/lib/operator";
import type { AreaState, V2Action, V2Area, V2Location, V2Overview } from "@/lib/seo-v2";
import { useFetch } from "@/lib/use-api";

const STATE_WORDS: Record<AreaState, string> = { ok: "Good", improve: "Can be better", missing: "Missing", unknown: "Not read yet" };
const STATE_TONE: Record<AreaState, "green" | "amber" | "red" | "gray"> = { ok: "green", improve: "amber", missing: "red", unknown: "gray" };

/** The optimisation dashboard: what is on the profile, what FlowQR found, what waits for you, what is confirmed on Google, and what failed. Counts and values only from the server. */
export function OptimizationCenter() {
  const { locationId } = useLocationScope();
  const { isAdmin, role } = useAuth();
  const toast = useToast();
  const ov = useFetch<V2Overview>("/seo/v2/overview", { location_id: locationId ?? "" });
  const [scanning, setScanning] = useState(false);
  const d = ov.data;

  async function scan() {
    setScanning(true);
    try {
      const r = await api<{ proposed: number; recommended: number }>("/agent/actions/scan", { method: "POST" });
      toast(r.proposed + r.recommended > 0 ? `Found ${r.proposed + r.recommended} improvement${r.proposed + r.recommended === 1 ? "" : "s"}.` : "Nothing new to suggest right now.");
      void ov.reload();
    } catch (e) { toast(errorMessage(e), "error"); } finally { setScanning(false); }
  }

  if (ov.loading && !d) return <Skeleton className="h-64" />;
  if (ov.error) return <Alert tone="error">{ov.error}</Alert>;
  if (!d || d.locations.length === 0) return null;
  const t = d.totals;
  const tiles: [string, number, string][] = [["Issues found", t.issues_detected, "on your profile"], ["Waiting for you", t.pending_approvals, "to approve"], ["Confirmed on Google", t.verified_last_90_days, "last 90 days"]];
  const closed = d.locations.some((l) => !l.gate.allowed);
  return (
    <section aria-label="Fix your profile" className="space-y-3 lg:space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-[18px] font-semibold leading-6">Fix your profile</h2>
          <p className="mt-0.5 max-w-prose text-[13px] text-muted">{d.how_it_works}</p>
        </div>
        {isAdmin && <Button size="sm" variant="secondary" onClick={() => void scan()} loading={scanning}>Look for improvements</Button>}
      </div>
      <dl className="grid grid-cols-3 gap-2">
        {tiles.map(([label, n, hint]) => (
          <div key={label} className="rounded-tile bg-surface p-3 shadow-card">
            <dt className="text-[13px] text-muted">{label}</dt><dd className="num text-[22px] font-semibold leading-7">{fmtNum(n)}</dd><dd className="text-[12px] text-muted">{hint}</dd>
          </div>
        ))}
      </dl>
      {closed && <p className="text-[13px] text-muted">Some fixes are shown to you but not made by FlowQr yet, because Google&rsquo;s rules on automated changes are still being confirmed.</p>}
      {d.locations.map((l) => <LocationBlock key={l.google_location_id} l={l} multi={d.locations.length > 1} canDecide={isAdmin} isOwner={role === "owner"} reload={() => void ov.reload()} />)}
    </section>
  );
}

function LocationBlock({ l, multi, canDecide, isOwner, reload }: { l: V2Location; multi: boolean; canDecide: boolean; isOwner: boolean; reload: () => void }) {
  const [inputsOpen, setInputsOpen] = useState(false);
  if (!l.profile_read) return <Alert tone="warning" title={l.title ?? "Google profile"}>{l.note ?? "FlowQR has not read this Google profile yet."}</Alert>;
  const a = l.actions;
  const history = [...a.failed, ...a.blocked, ...a.in_progress, ...a.verified];
  const needsLook = a.failed.length + a.blocked.length;
  return (
    <div className="space-y-3 lg:space-y-4">
      {multi && <h3 className="text-[15px] font-semibold">{l.title}</h3>}
      {l.google_changed && l.google_changed.length > 0 && <Alert tone="warning" title="Google changed some details itself">Google shows a different value for: {l.google_changed.join(", ")}. FlowQR will not suggest changes over these and never undoes Google&rsquo;s edits.</Alert>}
      {a.pending.length > 0 && <Card label="Waiting for you"><Title>Waiting for your approval</Title><ul className="mt-3 space-y-3">{a.pending.map((x) => <WaitingCard key={x.id} a={x} canDecide={canDecide} isOwner={isOwner} onChanged={reload} />)}</ul></Card>}
      <Card label="Profile areas"><Title>What needs attention</Title><AreaList areas={l.areas} gid={l.google_location_id} actions={[...a.pending, ...a.recommended, ...a.in_progress]} canDecide={canDecide} onInputs={() => setInputsOpen(true)} /></Card>
      <div id="owner-inputs" className="scroll-mt-24">
        <Card label="Your answers needed">
          <button type="button" aria-expanded={inputsOpen} onClick={() => setInputsOpen((o) => !o)} className="flex min-h-11 w-full items-center justify-between gap-3 text-left">
            <span><span className="block text-[16px] font-semibold">Questions only you can answer</span><span className="block text-[13px] text-muted">Holiday hours, services, attributes. FlowQR never guesses these.</span></span>
            <span aria-hidden className="text-[13px] font-semibold text-accent-ink">{inputsOpen ? "Hide" : "Show"}</span>
          </button>
          {inputsOpen && <OwnerInputs l={l} canDecide={canDecide} reload={reload} />}
        </Card>
      </div>
      {a.recommended.length > 0 && <Card label="Recommended"><Title>Recommended changes</Title><p className="mt-1 text-[13px] text-muted">Drafted and checked against your own facts. Open one to see the exact change.</p><ul className="mt-3 space-y-3">{a.recommended.map((x) => <Recommended key={x.id} a={x} canDecide={canDecide} reload={reload} />)}</ul></Card>}
      {history.length > 0 && (
        <Card label="History">
          <Accordion summary={`History: ${needsLook ? `${needsLook} need a look, ` : ""}${a.verified.length} confirmed on Google`}>
            <ul className="mt-2 divide-y divide-line">{history.slice(0, 8).map((x) => <Outcome key={x.id} a={x} />)}</ul>
          </Accordion>
        </Card>)}
    </div>
  );
}

function AreaList({ areas, gid, actions, canDecide, onInputs }: { areas: V2Area[]; gid: string; actions: V2Action[]; canDecide: boolean; onInputs: () => void }) {
  const [all, setAll] = useState(false);
  // An area whose change is already waiting for approval is shown once, in the approval card above, not a second time here.
  const waiting = new Set(actions.filter((a) => a.status === "pending_approval").map((a) => AREA_FOR_FIELD[a.field ?? ""]));
  const attention = areas.filter((x) => (x.state === "missing" || x.state === "improve") && !waiting.has(x.key));
  const shown = all ? areas : attention;
  return (
    <>
    {attention.length === 0 && !all && <p className="mt-3 text-[14px] text-muted">Nothing needs attention right now.</p>}
    <ul className="mt-3 divide-y divide-line">
      {shown.map((x) => {
        const step = areaStep(x, actions);
        return (
          <li key={x.key} className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1 py-2.5">
            <div className="min-w-[14rem] flex-1">
              <div className="flex flex-wrap items-center gap-2"><span className="text-[14px] font-semibold">{x.label}</span><Badge tone={STATE_TONE[x.state]}>{STATE_WORDS[x.state]}</Badge></div>
              <p className="mt-0.5 text-[13px] text-ink-700">{x.summary}</p>
              {x.note && <p className="mt-0.5 text-[12px] text-muted">{x.note}</p>}
              {x.fix && ["recommended_only", "unavailable_via_api", "edit_in_google"].includes(x.fix.mode) && step?.kind !== "info" && <p className="mt-0.5 text-[12px] text-muted">{x.fix.label}</p>}
            </div>
            {step && <AreaAction step={step} gid={gid} canDecide={canDecide} onInputs={onInputs} />}
          </li>);
      })}
    </ul>
    {areas.length > attention.length && <button type="button" onClick={() => setAll((v) => !v)} className="mt-2 inline-flex min-h-9 items-center text-[13px] font-semibold text-accent-ink hover:underline">{all ? "Show only what needs attention" : `Show all ${areas.length} areas`}</button>}
    </>
  );
}

/** What an area's button really does: open the prepared change, have the AI prepare it and then open it, jump to the questions only the owner can answer, or say in words why FlowQr cannot. */
function AreaAction({ step, gid, canDecide, onInputs }: { step: AreaStep; gid: string; canDecide: boolean; onInputs: () => void }) {
  const router = useRouter();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const cls = "inline-flex min-h-9 shrink-0 items-center gap-1 rounded-full bg-surface-2 px-3 text-[13px] font-semibold text-accent-ink ring-1 ring-inset ring-line hover:bg-accent-tint";
  if (step.kind === "info") return <p className="max-w-xs text-[12px] text-muted">{step.text}{step.href && <> <a href={step.href} target="_blank" rel="noreferrer" className="font-semibold text-accent-ink hover:underline">{step.linkLabel}</a></>}</p>;
  if (step.kind === "open") return <Link href={step.href} className={cls}>{step.label}<ArrowRight className="h-3.5 w-3.5" aria-hidden /></Link>;
  if (step.kind === "inputs") return <button type="button" className={cls} onClick={() => { onInputs(); setTimeout(() => document.getElementById("owner-inputs")?.scrollIntoView({ behavior: "smooth", block: "start" }), 50); }}>{step.label}<ArrowRight className="h-3.5 w-3.5" aria-hidden /></button>;
  async function prepare() {
    setBusy(true); setNote(null);
    try {
      const r = await api<PrepareResponse>("/operator/prepare", { method: "POST", body: { google_location_id: gid, area: step.kind === "prepare" ? step.area : "" } });
      if (r.change) router.push(`/ai/changes?focus=${encodeURIComponent(r.change.key)}`);
      else { setNote(r.message); toast(r.message, r.status === "cannot_prepare" ? "error" : undefined); }
    } catch (e) { setNote(errorMessage(e)); } finally { setBusy(false); }
  }
  return (
    <div className="flex max-w-xs flex-col items-end gap-1">
      <Button size="sm" variant="secondary" loading={busy} disabled={!canDecide} onClick={() => void prepare()}>{step.label}</Button>
      {!canDecide && <p className="text-[12px] text-muted">An owner or admin prepares changes.</p>}
      {note && <p role="status" className="text-right text-[12px] text-muted">{note}</p>}
    </div>
  );
}

function Diff({ a }: { a: V2Action }) {
  const lines = (xs: string[], tone: string) => xs.length === 0 ? <p className="text-[13px] text-muted">Nothing</p> : <ul className={clsx("space-y-0.5 text-[13px]", tone)}>{xs.slice(0, 12).map((s, i) => <li key={i}>{s}</li>)}{xs.length > 12 && <li className="text-muted">and {xs.length - 12} more</li>}</ul>;
  return (
    <div className="grid items-start gap-2 sm:grid-cols-[1fr_auto_1fr]">
      <div><p className="text-xs font-medium text-muted">On Google now</p><div className="mt-1 max-h-44 overflow-auto rounded-tile bg-surface-2 p-3">{lines(a.diff.before, "")}</div></div>
      <ArrowRight className="mx-auto mt-7 hidden h-4 w-4 text-muted sm:block" aria-hidden />
      <div><p className="text-xs font-medium text-muted">Would become</p><div className="mt-1 max-h-44 overflow-auto rounded-tile bg-accent-tint p-3">{lines(a.diff.after, "")}</div>{a.diff.added.length > 0 && <p className="mt-1 text-[12px] text-pos">Adds: {a.diff.added.slice(0, 4).join(", ")}{a.diff.added.length > 4 ? "…" : ""}</p>}{a.diff.removed.length > 0 && <p className="mt-0.5 text-[12px] text-neg">Removes: {a.diff.removed.join(", ")}</p>}</div>
    </div>
  );
}

function Recommended({ a, canDecide, reload }: { a: V2Action; canDecide: boolean; reload: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  async function dismiss() {
    setBusy(true);
    try { await api(`/agent/actions/${a.id}/reject`, { method: "POST", body: { reason: "Dismissed from the recommendations" } }); toast("Dismissed. FlowQR will not suggest this exact change again."); reload(); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(false); }
  }
  return (
    <li className="space-y-3 rounded-tile border border-line p-4">
      <div className="flex flex-wrap items-center gap-2"><span className="font-semibold">{a.label}</span><Badge tone="blue">Not made by FlowQR</Badge><Badge tone={a.policy_level === 3 ? "red" : "amber"}>{a.risk} risk</Badge></div>
      <p className="text-sm text-muted">{a.problem}</p>
      <Diff a={a} />
      <p className="text-sm"><span className="font-medium">Why: </span>{a.reason}</p>
      <p className="text-xs text-muted">{a.expected_outcome}</p>
      <div className="flex flex-wrap items-center gap-2"><Link href={`/ai/changes?focus=action:${a.id}`} className="inline-flex min-h-9 items-center gap-1 text-[13px] font-semibold text-accent-ink hover:underline">Open this change<ArrowRight className="h-3.5 w-3.5" aria-hidden /></Link>{canDecide && <Button size="sm" variant="secondary" onClick={() => void dismiss()} loading={busy}>Dismiss</Button>}</div>
    </li>
  );
}

function Outcome({ a }: { a: V2Action }) {
  const w = STATUS_WORDS[a.status];
  const Icon = a.status === "executed" ? CheckCircle2 : a.status === "failed" || a.status === "blocked" || a.status === "invalidated" ? ShieldAlert : CircleDashed;
  return (
    <li className="flex items-start gap-3 py-2.5">
      <Icon className={clsx("mt-0.5 h-4 w-4 shrink-0", a.status === "executed" ? "text-pos" : a.status === "failed" ? "text-neg" : "text-muted")} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-[14px] font-medium">{a.label}: {w.label}</p>
        {a.diff.added.length > 0 && <p className="line-clamp-2 text-[13px] text-ink-700">Added: {a.diff.added.slice(0, 3).join(", ")}{a.diff.added.length > 3 ? "…" : ""}</p>}
        {a.last_error && <p className="line-clamp-2 text-[13px] text-neg">{a.last_error}</p>}
        {a.executed_note && <p className="text-[12px] text-muted">{a.executed_note}</p>}
        <p className="text-[12px] text-muted">{timeAgo(a.verified_at ?? a.executed_at ?? a.created_at)}</p>
      </div>
    </li>
  );
}

function Performance({ p }: { p: NonNullable<V2Location["performance"]> }) {
  const diff = p.current != null && p.previous != null ? p.current - p.previous : null;
  return (
    <div className="mt-3">
      <p className="num text-[22px] font-semibold leading-7">{p.current != null ? fmtNum(p.current) : "–"}</p>
      <p className="text-[13px] text-muted">calls, directions, website visits, bookings and messages, {p.from} to {p.to}</p>
      {diff != null && <p className="mt-1 text-[13px]">{diff === 0 ? "The same as" : `${diff > 0 ? "+" : ""}${fmtNum(diff)} compared with`} the 28 days before ({fmtNum(p.previous ?? 0)}). This shows movement, not what caused it.</p>}
    </div>
  );
}

function OwnerInputs({ l, canDecide, reload }: { l: V2Location; canDecide: boolean; reload: () => void }) {
  const toast = useToast();
  const attrs = l.areas.find((x) => x.key === "attributes");
  const special = l.areas.find((x) => x.key === "special_hours");
  const [date, setDate] = useState(""), [closed, setClosed] = useState(true), [open, setOpen] = useState("09:00"), [close, setClose] = useState("14:00");
  const [svc, setSvc] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  async function post(kind: string, path: string, body: unknown, done: string) {
    setBusy(kind);
    try {
      const r = await api<{ status: string }>(path, { method: "POST", body });
      toast(r.status === "recommended" ? "Saved as a recommendation: FlowQR shows it to you but does not make it yet." : r.status === "blocked" ? "Checked, but it cannot be applied." : done);
      reload();
    } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); }
  }
  const bools = (attrs?.questions ?? []).filter((q) => q.type === "BOOL").slice(0, 6);
  return (
    <div className="mt-3 space-y-4">
      <div>
        <p className="text-[14px] font-semibold">Holiday or special hours</p>
        <p className="text-[13px] text-muted">{special?.summary ?? "Add a date you are closed or open different hours."}</p>
        <div className="mt-2 grid grid-cols-2 gap-2">
          <Input label="Date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          <label className="flex items-end gap-2 pb-2 text-[14px]"><input type="checkbox" checked={closed} onChange={(e) => setClosed(e.target.checked)} className="h-4 w-4" />Closed all day</label>
          {!closed && <><Input label="Opens" type="time" value={open} onChange={(e) => setOpen(e.target.value)} /><Input label="Closes" type="time" value={close} onChange={(e) => setClose(e.target.value)} /></>}
        </div>
        <Button size="sm" className="mt-2" disabled={!canDecide || !date} loading={busy === "sp"} onClick={() => void post("sp", "/seo/v2/special-hours", { google_location_id: l.google_location_id, entries: [closed ? { start: date, closed: true } : { start: date, open, close }] }, "Added for your approval.")}>Add this date</Button>
      </div>
      <div>
        <p className="text-[14px] font-semibold">Add a service</p>
        <p className="text-[13px] text-muted">Your existing services stay exactly as they are.</p>
        <div className="mt-2 flex gap-2"><div className="min-w-0 flex-1"><Input label="Service name" value={svc} onChange={(e) => setSvc(e.target.value)} maxLength={140} /></div><Button size="sm" className="self-end" disabled={!canDecide || svc.trim().length < 2} loading={busy === "sv"} onClick={() => void post("sv", "/seo/v2/services", { google_location_id: l.google_location_id, names: [svc.trim()] }, "Added for your approval.").then(() => setSvc(""))}>Add</Button></div>
      </div>
      {bools.length > 0 && (
        <div>
          <p className="text-[14px] font-semibold">Questions Google asks about your business</p>
          <p className="text-[13px] text-muted">FlowQR never guesses these. Answer only what you are sure of.</p>
          <ul className="mt-2 divide-y divide-line">{bools.map((q) => (
            <li key={q.name} className="flex items-center justify-between gap-2 py-2"><span className="min-w-0 text-[14px]">{q.label}</span>
              <span className="flex shrink-0 gap-1.5">{[["Yes", true], ["No", false]].map(([w, v]) => <Button key={String(w)} size="sm" variant="secondary" disabled={!canDecide} loading={busy === q.name + w} onClick={() => void post(q.name + String(w), "/seo/v2/attributes", { google_location_id: l.google_location_id, answers: [{ name: q.name, value: v }] }, "Answer saved for your approval.")}>{String(w)}</Button>)}</span></li>
          ))}</ul>
          {(attrs?.questions?.length ?? 0) > bools.length && <p className="mt-1 text-[12px] text-muted">{(attrs?.questions?.length ?? 0) - bools.length} more questions with other kinds of answers are not shown here yet.</p>}
        </div>
      )}
    </div>
  );
}

function Opportunities({ l, canDecide, reload }: { l: V2Location; canDecide: boolean; reload: () => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  async function track(term: string) {
    setBusy(term);
    try { await api(`/rank/keywords`, { method: "POST", params: { google_location_id: l.google_location_id }, body: { keyword: term } }); toast("Tracking it. FlowQR will measure where you show up."); reload(); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); }
  }
  return (
    <>
      <p className="mt-1 text-[13px] text-muted">Built from the services you listed, where you are, and what Google says people searched. No search volume or ranking is promised.</p>
      <ul className="mt-2 divide-y divide-line">
        {l.opportunities.slice(0, 8).map((o) => (
          <li key={o.term} className="flex items-start justify-between gap-3 py-2.5">
            <div className="min-w-0"><p className="text-[14px] font-medium">{o.term}</p><p className="text-[12px] text-muted">{o.evidence.slice(0, 2).join(" · ")}{o.in_description ? " · already in your description" : ""}</p></div>
            {canDecide && <Button size="sm" variant="secondary" loading={busy === o.term} onClick={() => void track(o.term)}>Track</Button>}
          </li>
        ))}
      </ul>
    </>
  );
}
