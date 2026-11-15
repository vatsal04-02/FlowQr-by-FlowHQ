"use client";
import { RefreshCw } from "lucide-react";
import { useState } from "react";
import { HealthCard } from "@/components/agent/HealthCard";
import { TaskCard } from "@/components/agent/TaskCard";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert, EmptyState, PageHeader, Skeleton } from "@/components/ui/Card";
import { useToast } from "@/components/ui/Toast";
import type { TasksResponse } from "@/lib/agent";
import { api, ApiError, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

export default function DailyPlan() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const { data, error, loading, reload } = useFetch<TasksResponse>("/agent/tasks", { scope: "today" });
  const [busy, setBusy] = useState<"plan" | "google" | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  async function run(kind: "plan" | "google") {
    setBusy(kind); setProblem(null);
    try {
      if (kind === "google") { const r = await api<{ locations: { ok: boolean; error: string | null; title: string }[] }>("/agent/google/refresh", { method: "POST" }); const bad = r.locations.filter((l) => !l.ok); if (bad.length) setProblem(bad.map((b) => `${b.title}: ${b.error}`).join(" ")); else toast("Google data refreshed."); }
      else { const r = await api<{ created: number }>("/agent/plan/run", { method: "POST" }); toast(r.created ? `${r.created} new task${r.created === 1 ? "" : "s"} added.` : "Nothing new: your plan is up to date."); }
      await reload();
    } catch (e) { setProblem(e instanceof ApiError && e.status === 402 ? "Your plan is inactive. Choose a plan to refresh the agent." : errorMessage(e)); } finally { setBusy(null); }
  }
  const tasks = data?.tasks ?? [];
  const open = tasks.filter((t) => !["published", "done", "dismissed"].includes(t.status));
  const finished = tasks.filter((t) => ["published", "done"].includes(t.status));

  return (
    <>
      <PageHeader title="Today's plan" subtitle={data?.last_plan_date ? `Built from your real data on ${fmtDate(data.last_plan_date)}. Nothing is sent to Google without your approval.` : "Built from your real data. Nothing is sent to Google without your approval."}
        actions={isAdmin ? <><Button size="sm" variant="secondary" icon={<RefreshCw className="h-4 w-4" />} loading={busy === "google"} onClick={() => void run("google")}>Refresh from Google</Button><Button size="sm" loading={busy === "plan"} onClick={() => void run("plan")}>Update plan</Button></> : undefined} />
      {problem && <div className="mb-4"><Alert tone="error" title="Something didn't go through">{problem}</Alert></div>}
      {data && tasks.filter((t) => t.status !== "dismissed").length > 0 && (() => {
        const all = tasks.filter((t) => t.status !== "dismissed").length, waiting = open.filter((t) => t.status === "awaiting_approval").length;
        return (
          <section aria-label="Today's progress" className="on-navy mb-4 rounded-2xl bg-navy p-4 text-white sm:p-5">
            <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-3">
              <div><p className="text-xl font-bold">{finished.length} of {all} done today</p><p className="mt-0.5 text-sm text-white/75">{waiting > 0 ? `${waiting} waiting for your approval` : open.length ? `${open.length} still to do` : "Everything is handled."}</p></div>
              <div className="min-w-[200px] flex-1 sm:max-w-sm"><div role="progressbar" aria-label="Tasks finished today" aria-valuenow={finished.length} aria-valuemin={0} aria-valuemax={all} className="h-2.5 overflow-hidden rounded-full bg-white/15"><div className="h-full rounded-full bg-fq transition-[width] duration-500" style={{ width: `${(finished.length / all) * 100}%` }} /></div></div>
            </div>
          </section>);
      })()}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px]">
        <section aria-label="Tasks" className="min-w-0 space-y-3">
          {error && <Alert tone="error">{error}</Alert>}
          {loading && !data ? <Skeleton className="h-64" /> : open.length === 0 ? (
            <EmptyState title={finished.length ? "All done for now" : "No tasks yet"} action={isAdmin ? <Button size="sm" onClick={() => void run("plan")} loading={busy === "plan"}>Build today&rsquo;s plan</Button> : undefined}>
              {finished.length ? "Everything in today's plan has been handled." : "The plan is built from real reviews, your Google profile and your knowledge base. If nothing is shown, either everything is in order or the agent hasn't run yet."}</EmptyState>
          ) : <ul className="space-y-3">{open.map((t) => <TaskCard key={t.id} t={t} onChange={() => void reload()} />)}</ul>}
          {finished.length > 0 && <div><h2 className="mb-2 mt-5 text-sm font-semibold text-ink-500">Finished in the last day</h2><ul className="space-y-3">{finished.map((t) => <TaskCard key={t.id} t={t} onChange={() => void reload()} />)}</ul></div>}
        </section>
        <aside className="min-w-0 space-y-4"><HealthCard />
          <div className="text-[13px] text-ink-500"><LinkButton href="/ai/tasks" size="sm" variant="secondary">All recommendations</LinkButton> <LinkButton href="/ai/approvals" size="sm" variant="secondary">Approvals</LinkButton></div></aside>
      </div>
    </>
  );
}
