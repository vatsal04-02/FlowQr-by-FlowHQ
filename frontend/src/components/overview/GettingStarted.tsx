"use client";
import { Check, ChevronDown, Lock } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { LinkButton } from "@/components/ui/Button";
import { Meter } from "@/components/ui/kit";
import { useFetch } from "@/lib/use-api";

interface Step { id: string; title: string; why: string; done: boolean; optional: boolean; href: string; cta: string; note: string | null; locked: string | null }
interface Checklist { steps: Step[]; required_total: number; required_done: number; complete: boolean; next: string | null }

/**
 * What is left to set up, from the real records (never sample data): a step is done when the thing exists. On Home it is one slim card: the progress and the single next step,
 * with the full list one tap away. It disappears once every required step is done.
 */
export function GettingStarted() {
  const { data } = useFetch<Checklist>("/workspace/getting-started");
  const [all, setAll] = useState(false);
  if (!data || data.complete) return null;
  // the plan is handled by the account strip: when choosing a plan is all that is left, this card adds nothing
  if (data.steps.filter((x) => !x.done && !x.optional && !x.locked).every((x) => x.id === "plan")) return null;
  const next = data.steps.find((s) => s.id === data.next) ?? data.steps.find((s) => !s.done && !s.locked);
  return (
    <section aria-labelledby="gs-h" className="panel mb-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h2 id="gs-h" className="text-[15px] font-semibold">Setup</h2>
        <p className="num text-[13px] text-muted">{data.required_done}/{data.required_total}</p>
      </div>
      <div className="mt-2"><Meter value={data.required_done} max={data.required_total} tone="ok" label="Setup progress" /></div>
      {next && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
          <p className="min-w-0 flex-1 basis-56 text-[14px] font-semibold">{next.title}</p>
          <LinkButton href={next.href} size="md" variant="secondary">{next.cta}</LinkButton>
        </div>
      )}
      <button type="button" aria-expanded={all} onClick={() => setAll((v) => !v)} className="mt-2 inline-flex min-h-11 items-center gap-1 text-[13px] font-semibold text-ink-700 hover:text-ink hover:underline sm:min-h-9">
        {all ? "Hide steps" : "All steps"}<ChevronDown className={`h-3.5 w-3.5 transition-transform ${all ? "rotate-180" : ""}`} aria-hidden />
      </button>
      {all && (
        <ol className="mt-1 divide-y divide-line">
          {data.steps.map((s) => (
            <li key={s.id} className="flex items-start gap-3 py-2.5">
              <span aria-hidden className={`mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs ${s.done ? "bg-pos text-pure-white dark:text-pure-ink" : "bg-surface-2 text-muted"}`}>{s.done ? <Check className="h-3.5 w-3.5" strokeWidth={3} /> : s.locked ? <Lock className="h-3 w-3" /> : ""}</span>
              <div className="min-w-0 flex-1">
                <p className={`text-[14px] ${s.done ? "text-muted line-through" : "font-medium"}`}>{s.title}{s.optional && !s.done && <span className="ml-2 text-xs font-normal text-muted">optional</span>}</p>
                {!s.done && s.locked && <p className="text-xs text-muted">{s.locked}</p>}
              </div>
              {!s.done && !s.locked && s.id !== data.next && <Link href={s.href} className="inline-flex min-h-11 items-center text-[13px] font-semibold text-accent-ink hover:underline sm:min-h-9">{s.cta}</Link>}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
