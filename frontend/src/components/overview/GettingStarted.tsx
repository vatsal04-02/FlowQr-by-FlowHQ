"use client";
import { Check, Lock } from "lucide-react";
import Link from "next/link";
import { LinkButton } from "@/components/ui/Button";
import { Meter } from "@/components/ui/kit";
import { useFetch } from "@/lib/use-api";

interface Step { id: string; title: string; why: string; done: boolean; optional: boolean; href: string; cta: string; note: string | null; locked: string | null }
interface Checklist { steps: Step[]; required_total: number; required_done: number; complete: boolean; next: string | null }

/**
 * What is left to do, from the real records (never sample data): a step is done when the thing exists. Optional steps are marked as such, steps the plan does not include
 * show which plan adds them, and the panel disappears once every required step is done.
 */
export function GettingStarted() {
  const { data } = useFetch<Checklist>("/workspace/getting-started");
  if (!data || data.complete) return null;
  return (
    <section aria-labelledby="gs-h" className="panel mb-5 p-4 sm:mb-6 sm:p-6">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-3">
        <h2 id="gs-h" className="text-lg font-semibold">Getting started</h2>
        <p className="text-[13px] text-muted">{data.required_done} of {data.required_total} essential steps done</p>
      </div>
      <Meter value={data.required_done} max={data.required_total} tone="ok" label="Getting started progress" />
      <ol className="mt-4 divide-y divide-line">
        {data.steps.map((s) => (
          <li key={s.id} className={`flex flex-wrap items-start gap-3 py-3 ${s.id === data.next ? "bg-accent-tint -mx-2 rounded-tile px-2" : ""}`}>
            <span aria-hidden className={`mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full text-xs ${s.done ? "bg-pos text-pure-white dark:text-pure-ink" : "bg-surface-2 text-muted"}`}>{s.done ? <Check className="h-3.5 w-3.5" /> : s.locked ? <Lock className="h-3 w-3" /> : ""}</span>
            <div className="min-w-0 flex-1 basis-56">
              <p className={`text-[15px] ${s.done ? "text-muted line-through" : "font-semibold"}`}>{s.title}{s.optional && !s.done && <span className="ml-2 text-xs font-normal text-muted">optional</span>}<span className="sr-only">{s.done ? " (done)" : s.locked ? ` (${s.locked})` : ""}</span></p>
              {!s.done && <p className="mt-0.5 text-sm text-muted">{s.why}</p>}
              {!s.done && s.note && <p className="mt-1 text-sm text-ink-700">{s.note}</p>}
              {!s.done && s.locked && <p className="mt-1 text-xs font-medium text-muted">{s.locked}</p>}
            </div>
            {!s.done && !s.locked && (s.id === data.next ? <LinkButton href={s.href} size="md" variant="brand">{s.cta}</LinkButton> : <Link href={s.href} className="inline-flex min-h-11 items-center text-sm font-semibold text-accent-ink hover:underline">{s.cta}</Link>)}
          </li>
        ))}
      </ol>
    </section>
  );
}
