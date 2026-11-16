"use client";
import clsx from "clsx";
import { ArrowRight, Check, PenLine, Send } from "lucide-react";
import { useState } from "react";
import { Alert, PageHeader, Skeleton } from "@/components/ui/Card";
import { Panel } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useFetch } from "@/lib/use-api";

interface S { daily_plan: boolean; auto_draft_replies: boolean; auto_draft_posts: boolean; auto_publish: boolean; notes: Record<string, string> }

/** A real switch (checkbox with role="switch", so keyboards and screen readers work) drawn as an on/off toggle. */
function Toggle({ id, label, help, on, disabled, onChange }: { id: string; label: string; help: string; on: boolean; disabled?: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className="flex items-start justify-between gap-4 py-3.5">
      <div className="min-w-0"><label htmlFor={id} className="text-sm font-semibold text-navy">{label}</label><p className="mt-0.5 text-[13px] leading-snug text-ink-500">{help}</p></div>
      <label htmlFor={id} className={clsx("relative mt-0.5 inline-flex shrink-0", disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer")}>
        <input id={id} type="checkbox" role="switch" aria-checked={on} checked={on} disabled={disabled} onChange={(e) => onChange(e.target.checked)} className="peer absolute inset-0 z-10 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed" />
        <span aria-hidden className="h-7 w-12 rounded-full bg-ink-300 transition-colors peer-checked:bg-fq peer-focus-visible:ring-2 peer-focus-visible:ring-navy peer-focus-visible:ring-offset-2" />
        <span aria-hidden className="absolute left-0.5 top-0.5 h-6 w-6 rounded-full bg-white shadow transition-transform peer-checked:translate-x-5" />
        <span className="ml-2 w-7 self-center text-[13px] font-semibold text-ink-700" aria-hidden>{on ? "On" : "Off"}</span>
      </label>
    </div>
  );
}

/** How every automation works, in one picture: the AI prepares, a person approves, only then does anything reach Google. */
function Flow() {
  const nodes = [
    { icon: PenLine, title: "Your AI assistant prepares", body: "Replies and posts, written from your Business Brain.", tone: "bg-white text-navy" },
    { icon: Check, title: "You approve", body: "Edit it, approve it, or say no. Always you.", tone: "bg-fq text-pure-ink" },
    { icon: Send, title: "It goes to Google", body: "Only after you say yes.", tone: "bg-white text-navy" },
  ];
  return (
    <ol aria-label="How automations work" className="grid gap-2 sm:grid-cols-[1fr_auto_1fr_auto_1fr] sm:items-stretch">
      {nodes.flatMap((n, i) => [
        <li key={n.title} className={clsx("rounded-xl p-4 ring-1 ring-ink-100", n.tone)}>
          <span aria-hidden className={clsx("grid h-9 w-9 place-items-center rounded-full", i === 1 ? "bg-white/70" : "bg-brand-100 text-brand-800")}><n.icon className="h-[18px] w-[18px]" strokeWidth={2} /></span>
          <p className="mt-3 text-sm font-bold">{n.title}</p><p className={clsx("mt-0.5 text-[13px] leading-snug", i === 1 ? "text-pure-ink" : "text-ink-700")}>{n.body}</p>
        </li>,
        ...(i < 2 ? [<li key={`a${i}`} aria-hidden className="grid place-items-center text-brand-700"><ArrowRight className="h-5 w-5 rotate-90 sm:rotate-0" /></li>] : []),
      ])}
    </ol>
  );
}

interface Cap { id: string; name: string; independent: string[]; needs_approval: string[]; verification: string; never: string[]; sources: string }
interface Pipe { collect: { snapshots: number; last_fetch: string | null }; recommend: { open_suggestions: number }; prepare: { drafted: number }; approve: { waiting: number }; publish: { queued: number; published_30d: number }; verify: { confirmed_by_google_30d: number; published_30d: number }; failed: number }
interface Autonomy { stages: { id: string; label: string; actor: string }[]; capabilities: Cap[]; pipeline: Pipe; rule: string }

/** The six capabilities as one agent: what it does alone, what waits for you, how each result is proven, and where your work is right now. */
function Matrix() {
  const { data } = useFetch<Autonomy>("/agent/autonomy");
  if (!data) return <Skeleton className="h-40" />;
  const p = data.pipeline;
  const live: Record<string, string> = {
    collect: `${p.collect.snapshots} location${p.collect.snapshots === 1 ? "" : "s"} read`, recommend: `${p.recommend.open_suggestions} suggestion${p.recommend.open_suggestions === 1 ? "" : "s"}`, prepare: `${p.prepare.drafted} drafted`,
    approve: `${p.approve.waiting} waiting for you`, publish: `${p.publish.queued} queued · ${p.publish.published_30d} live (30 days)`, verify: `${p.verify.confirmed_by_google_30d} of ${p.verify.published_30d} confirmed by Google`, report: "Activity page",
  };
  return (
    <Panel title="One agent, six jobs" meta="what it does alone and what needs you">
      <ol aria-label="Agent workflow" className="mb-5 grid gap-2 sm:grid-cols-4 lg:grid-cols-8">
        {data.stages.map((st) => (
          <li key={st.id} className={clsx("rounded-xl p-3 ring-1 ring-ink-100", st.actor === "owner" ? "bg-fq text-pure-ink" : "bg-white")}>
            <p className="text-[13px] font-bold">{st.label}</p><p className="mt-0.5 text-xs text-ink-500">{st.actor === "owner" ? "You" : st.actor === "agent" ? "Agent" : "System"}</p>
            <p className="mt-1.5 text-xs font-semibold tabular-nums text-ink-700">{live[st.id] ?? ""}</p>
          </li>))}
      </ol>
      {p.failed > 0 && <div className="mb-4"><Alert tone="warning" title={`${p.failed} item${p.failed === 1 ? "" : "s"} failed`}>See the reason on the Activity page. Nothing failed is shown as done.</Alert></div>}
      <div className="grid gap-3 lg:grid-cols-2">
        {data.capabilities.map((c) => (
          <details key={c.id} className="rounded-xl bg-white p-4 ring-1 ring-ink-100">
            <summary className="cursor-pointer text-sm font-bold text-navy">{c.name}</summary>
            <div className="mt-3 space-y-3 text-[13px] leading-snug text-ink-700">
              <div><p className="font-semibold text-navy">By itself</p><ul className="ml-4 list-disc">{c.independent.map((x) => <li key={x}>{x}</li>)}</ul></div>
              <div><p className="font-semibold text-navy">Needs your approval</p><ul className="ml-4 list-disc">{c.needs_approval.map((x) => <li key={x}>{x}</li>)}</ul></div>
              <div><p className="font-semibold text-navy">How it is verified</p><p>{c.verification}</p></div>
              <div><p className="font-semibold text-navy">Never</p><ul className="ml-4 list-disc">{c.never.map((x) => <li key={x}>{x}</li>)}</ul></div>
              <p className="text-xs text-ink-500">Data: {c.sources}</p>
            </div>
          </details>))}
      </div>
      <p className="mt-4 text-sm font-semibold text-navy">{data.rule}</p>
    </Panel>
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
      <PageHeader title="Helpers" subtitle="Choose what your assistant may prepare for you. Nothing goes live without your approval." />
      {error && <Alert tone="error">{error}</Alert>}
      {!isAdmin && <div className="mb-4"><Alert tone="info">Only owners and admins can change automations.</Alert></div>}
      {!data ? <Skeleton className="h-48" /> : (
        <div className="space-y-4">
          <Flow />
          <Panel title="Preparation (safe)" meta="these only prepare work for you"><div className="divide-y divide-ink-100">
            <Toggle id="plan" label="Build a daily plan" on={data.daily_plan} disabled={!isAdmin || busy} onChange={(v) => void set({ daily_plan: v })} help="Once a day (after 6am your time) the agent refreshes what Google says and lists what needs attention. It changes nothing on Google." />
            <Toggle id="posts" label="Write a daily Google post" on={data.auto_draft_posts} disabled={!isAdmin || busy} onChange={(v) => void set({ auto_draft_posts: v })} help={data.notes.auto_draft_posts} />
            <Toggle id="draft" label="Draft replies to new reviews" on={data.auto_draft_replies} disabled={!isAdmin || busy} onChange={(v) => void set({ auto_draft_replies: v })} help={data.notes.auto_draft_replies} />
          </div></Panel>
          <Panel title="Publishing" meta="not available">
            <Toggle id="pub" label="Publish automatically" on={false} disabled onChange={() => undefined} help={data.notes.auto_publish} />
          </Panel>
          <Matrix />
          <Panel title="What runs on its own">
            <ul className="ml-5 list-disc space-y-1 text-sm text-ink-700"><li>Every few minutes: due posts you approved are sent to Google at the time you chose.</li><li>Every 30 minutes: Google reviews are synced.</li><li>Every 15 minutes: replies you approved that failed for a temporary reason are retried (never ones you did not approve).</li><li>Daily: customer review-assistant text older than your retention period is deleted.</li></ul>
          </Panel>
        </div>)}
    </>
  );
}
