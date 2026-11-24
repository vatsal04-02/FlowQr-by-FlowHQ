"use client";
import clsx from "clsx";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { ChangeCard } from "@/components/operator/ChangeCard";
import { LinkButton } from "@/components/ui/Button";
import { Alert, PageHeader, Skeleton } from "@/components/ui/Card";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { MANUAL_EDITOR, prepareHeadline, type Category, type PendingResponse, type PrepareResponse } from "@/lib/operator";
import { useFetch } from "@/lib/use-api";

type Outcome = { tone: "success" | "warning" | "error"; text: string };

/** AI Recommendations & Pending Changes: everything FlowQr prepared that waits for a person, in one place, from the tables that already hold it. A link from a recommendation (`?prepare=<area>`)
 * has the AI draft the change on arrival and opens it; `?focus=<id>` opens one that already exists. */
export default function ChangesPage() {
  return <Suspense><Inner /></Suspense>;
}

function Inner() {
  const { isAdmin } = useAuth();
  const router = useRouter();
  const sp = useSearchParams();
  const [cat, setCat] = useState<Category | "all">("all");
  const list = useFetch<PendingResponse>("/operator/pending");
  const [outcomes, setOutcomes] = useState<Record<string, Outcome>>({});
  const [prep, setPrep] = useState<{ state: "working" | "done" | "error"; res?: PrepareResponse; error?: string; area: string } | null>(null);
  const started = useRef<string | null>(null);
  const prepare = sp.get("prepare"), location = sp.get("location"), focus = sp.get("focus");

  useEffect(() => {
    const k = prepare && location ? `${prepare}:${location}` : null;
    if (!k || started.current === k) return;
    started.current = k;
    setPrep({ state: "working", area: prepare! });
    api<PrepareResponse>("/operator/prepare", { method: "POST", body: { google_location_id: location, area: prepare } })
      .then((res) => {
        setPrep({ state: "done", res, area: prepare! });
        void list.reload();
        if (res.change) router.replace(`/ai/changes?focus=${encodeURIComponent(res.change.key)}`, { scroll: false });
      })
      .catch((e) => setPrep({ state: "error", error: errorMessage(e), area: prepare! }));
  }, [prepare, location]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!focus || !list.data) return;
    document.getElementById(`change-${focus}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focus, list.data]);

  const d = list.data;
  const items = (d?.items ?? []).filter((i) => cat === "all" || i.category === cat);
  const manual = prep?.area ? MANUAL_EDITOR[prep.area] : undefined;

  return (
    <>
      <PageHeader title="AI recommendations & pending changes" subtitle="FlowQr drafts the exact change, shows you BEFORE and AFTER, and applies it only after you approve. A change counts as done only after Google confirms it." />
      <div className="space-y-4">
        {prep?.state === "working" && <Alert tone="info" title="FlowQr is preparing this change">The AI is reading your profile and your Business Brain and writing the complete change. This can take up to half a minute.</Alert>}
        {prep?.state === "error" && <Alert tone="error" title="Could not prepare this change">{prep.error}</Alert>}
        {prep?.state === "done" && prep.res && (
          <Alert tone={prep.res.status === "prepared" || prep.res.status === "already_prepared" ? "success" : prep.res.status === "cannot_prepare" ? "error" : "info"} title={prepareHeadline(prep.res.status)}>
            {!prep.res.message.startsWith(prepareHeadline(prep.res.status).replace(/\.$/, "")) && <p>{prep.res.message}</p>}
            {prep.res.status === "needs_owner_input" && <p className="mt-1"><Link href="/seo" className="font-semibold text-accent-ink hover:underline">Open Fix your profile</Link> and answer under &ldquo;Tell us what we cannot know&rdquo;.</p>}
            {(prep.res.status === "nothing_to_change" || prep.res.status === "cannot_prepare") && manual && <p className="mt-1">You can still change it yourself: <Link href={manual.href} className="font-semibold text-accent-ink hover:underline">{manual.label}</Link>.</p>}
          </Alert>)}
        {Object.entries(outcomes).map(([k, o]) => <Alert key={k} tone={o.tone}>{o.text}</Alert>)}

        <div role="tablist" aria-label="Kind of change" className="flex flex-wrap gap-2">
          {[{ key: "all" as const, label: "All", n: d?.total ?? 0 }, ...(d?.categories ?? []).map((c) => ({ key: c.key, label: c.label, n: d?.counts[c.key] ?? 0 }))].map((c) => (
            <button key={c.key} role="tab" aria-selected={cat === c.key} onClick={() => setCat(c.key)}
              className={clsx("min-h-9 rounded-full px-3.5 text-[13px] font-semibold ring-1 ring-inset", cat === c.key ? "bg-navy text-white ring-navy" : "bg-surface text-ink-700 ring-line hover:bg-surface-2")}>
              {c.label} <span className="num ml-1 opacity-80">{c.n}</span>
            </button>))}
        </div>

        {list.error && <Alert tone="error">{list.error}</Alert>}
        {list.loading && !d ? <Skeleton className="h-64" /> : items.length === 0 ? (
          <div className="rounded-tile bg-surface p-6 text-center shadow-card">
            <p className="font-semibold">{d?.total ? "Nothing in this group." : "Nothing is waiting for you."}</p>
            <p className="mx-auto mt-1 max-w-md text-sm text-muted">Ask the operator to look at your profile, or open a profile area and prepare a specific change.</p>
            <div className="mt-3 flex flex-wrap justify-center gap-2"><LinkButton href="/ai/operator" size="sm">Ask the AI Operator</LinkButton><LinkButton href="/seo" size="sm" variant="secondary">Fix your profile</LinkButton></div>
          </div>
        ) : (
          <ul className="space-y-3">{items.map((i) => <ChangeCard key={i.key} item={i} canDecide={isAdmin} focused={focus === i.key} onChanged={() => void list.reload()} onDone={(k, o) => setOutcomes((p) => ({ ...p, [k]: o }))} />)}</ul>)}
      </div>
    </>
  );
}
