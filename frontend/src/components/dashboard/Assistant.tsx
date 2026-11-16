"use client";
import clsx from "clsx";
import { AlertTriangle, ArrowRight, Check, Clock, Lightbulb } from "lucide-react";
import Link from "next/link";
import { LinkButton } from "@/components/ui/Button";
import { LogoMark } from "@/components/ui/Brand";
import { Skeleton } from "@/components/ui/Card";
import type { Activity, Task } from "@/lib/agent";
import type { Todo } from "@/lib/dashboard";
import { timeAgo } from "@/lib/format";
import { Hint } from "./Hint";

const ICON = { bad: AlertTriangle, warn: Clock, info: Lightbulb } as const;
const LABEL = { bad: "Needs a look", warn: "Waiting for you", info: "Suggested" } as const;
const SHOWN = 4;

/** What the assistant has really finished: the latest step of each task that reached "published" or "done". Never padded. */
function finished(activity: Activity | null) {
  const latest = new Map<string, Activity["events"][number]>();
  for (const e of activity?.events ?? []) { const cur = latest.get(e.task); if (!cur || e.at > cur.at) latest.set(e.task, e); }
  return [...latest.values()].filter((e) => e.to === "published" || e.to === "done").sort((a, b) => b.at.localeCompare(a.at)).slice(0, 4);
}

export function Assistant({ todos, tasks, tasksError, activity, loading }: { todos: Todo[]; tasks: Task[] | null; tasksError: string | null; activity: Activity | null; loading: boolean }) {
  const n = todos.length;
  const live = (tasks ?? []).filter((t) => t.status !== "dismissed");
  const done = live.filter((t) => t.status === "published" || t.status === "done").length;
  const doneList = finished(activity);
  const noPlanYet = !!tasks && tasks.length === 0 && !activity?.last_plan_date;
  return (
    <section aria-labelledby="assistant-h" className="on-navy overflow-hidden rounded-2xl bg-navy text-white">
      <div className="grid gap-6 p-5 sm:p-7 lg:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] lg:gap-8">
        <div className="min-w-0">
          <p className="flex items-center gap-2 text-sm font-semibold text-flow-100"><LogoMark size={20} variant="onDark" />Your AI assistant<Hint dark label="Your AI assistant" text="FlowQR's assistant looks at your reviews, Google profile and card activity each morning and lists what to do. It writes drafts for you; it never posts anything without your approval." /></p>
          {loading ? <Skeleton className="mt-4 h-24 !bg-white/10" /> : (
            <>
              <h2 id="assistant-h" className="mt-3 text-2xl font-bold leading-tight tracking-tight sm:text-[28px]">
                {n > 0 ? `Your AI assistant has ${n} ${n === 1 ? "thing" : "things"} to help with today.` : noPlanYet ? "Your AI assistant hasn't made today's plan yet." : "You're all caught up."}
              </h2>
              {tasksError && <p className="mt-2 text-sm text-red-200">We couldn&rsquo;t load today&rsquo;s plan just now. {tasksError}</p>}
              {live.length > 0 && (
                <div className="mt-4 max-w-md">
                  <p className="flex justify-between text-[13px] text-white/80"><span>Today&rsquo;s plan</span><span className="num">{done} of {live.length} finished</span></p>
                  <div role="progressbar" aria-label="Tasks finished today" aria-valuenow={done} aria-valuemin={0} aria-valuemax={live.length} className="mt-1.5 h-2 overflow-hidden rounded-full bg-white/15">
                    <div className="h-full rounded-full bg-fq transition-[width] duration-500" style={{ width: `${(done / live.length) * 100}%` }} />
                  </div>
                </div>
              )}
              {n === 0 && !noPlanYet && <p className="mt-2 max-w-md text-sm text-white/75">Every review has an answer and nothing is waiting for you. Your assistant checks again tomorrow morning.</p>}
              {noPlanYet && <div className="mt-4"><LinkButton href="/ai/today" variant="brand" size="lg" icon={<ArrowRight className="h-4 w-4" />}>Open AI Growth</LinkButton></div>}

              {n > 0 && (
                <ul className="mt-5 space-y-2.5">
                  {todos.slice(0, SHOWN).map((t, i) => {
                    const Icon = ICON[t.tone];
                    return (
                      <li key={t.id} className="fq-rise rounded-xl bg-white/[.07] p-3.5 sm:p-4" style={{ ["--d" as string]: `${i * 60}ms` }}>
                        <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
                          <span aria-hidden className={clsx("grid h-9 w-9 shrink-0 place-items-center rounded-full", t.tone === "bad" ? "bg-red-500/20 text-red-200" : t.tone === "warn" ? "bg-fq/20 text-flow-400" : "bg-white/10 text-white")}><Icon className="h-[18px] w-[18px]" strokeWidth={2} /></span>
                          <div className="min-w-0 flex-1 basis-56">
                            <p className="text-[15px] font-semibold leading-snug">{t.title}</p>
                            <p className="mt-0.5 text-[13px] leading-snug text-white/70"><span className="font-semibold text-white/90">{LABEL[t.tone]}.</span> {t.detail}</p>
                          </div>
                          <LinkButton href={t.href} size="md" variant={i === 0 ? "brand" : "inverse"} className="w-full sm:w-auto">{t.cta}</LinkButton>
                        </div>
                      </li>
                    );
                  })}
                </ul>
              )}
              {n > SHOWN && <Link href="/ai/today" className="mt-3 inline-flex min-h-11 items-center gap-1 text-sm font-semibold text-flow-400 hover:underline">and {n - SHOWN} more in AI Growth<ArrowRight className="h-3.5 w-3.5" aria-hidden /></Link>}
            </>
          )}
        </div>

        <aside aria-labelledby="done-h" className="min-w-0 self-start rounded-xl bg-white/[.06] p-4 sm:p-5">
          <h3 id="done-h" className="text-sm font-semibold">What your AI assistant has done</h3>
          {loading ? <Skeleton className="mt-3 h-24 !bg-white/10" /> : doneList.length === 0 ? (
            <p className="mt-2 text-sm leading-relaxed text-white/70">Nothing finished yet. When a reply or post you approved goes out, it shows here with the time.</p>
          ) : (
            <ul className="mt-3 space-y-3">
              {doneList.map((e) => (
                <li key={`${e.task}-${e.at}`} className="flex gap-2.5">
                  <span aria-hidden className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-green-500/25 text-green-200"><Check className="h-3 w-3" strokeWidth={3} /></span>
                  <div className="min-w-0"><p className="text-sm font-medium leading-snug">{e.task}</p><p className="text-[13px] text-white/65">{e.to === "published" ? "Published on Google" : "Done"} · {timeAgo(e.at)}</p></div>
                </li>))}
            </ul>
          )}
          <Link href="/ai/activity" className="mt-4 inline-flex min-h-11 items-center gap-1 text-sm font-semibold text-flow-400 hover:underline sm:min-h-8">See everything it has done<ArrowRight className="h-3.5 w-3.5" aria-hidden /></Link>
        </aside>
      </div>
    </section>
  );
}
