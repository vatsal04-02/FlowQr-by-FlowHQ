"use client";
import clsx from "clsx";
import { AlertTriangle, RefreshCw, Search } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams, useSelectedLayoutSegment } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { Button, LinkButton } from "@/components/ui/Button";
import { Skeleton, Stars } from "@/components/ui/Card";
import { FilterSelect } from "@/components/ui/Form";
import { Status } from "@/components/ui/kit";
import { useToast } from "@/components/ui/Toast";
import { REPLY_STATE, ReviewsCtx } from "@/components/reviews-ctx";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { timeAgo } from "@/lib/format";
import type { Location, Review } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

const PAGE = 25;
const STATES = [["", "All"], ["none", "To reply"], ["draft", "Drafts"], ["failed", "Failed"], ["published", "Replied"]] as const;

export default function ReviewsLayout({ children }: { children: ReactNode }) {
  return <Suspense><Workspace>{children}</Workspace></Suspense>;
}

/** Master / detail workspace. The list lives in the layout so filters, scroll and selection survive moving between reviews. */
function Workspace({ children }: { children: ReactNode }) {
  const seg = useSelectedLayoutSegment();
  const sp = useSearchParams();
  const router = useRouter();
  const toast = useToast();
  const { isAdmin } = useAuth();
  const locs = useFetch<Location[]>("/locations");
  const google = useFetch<{ configured: boolean; connections: { status: string }[] }>("/google/status");
  const [f, setF] = useState({ location_id: "", rating: "", reply_state: sp.get("state") ?? "", search: sp.get("q") ?? "" });
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [syncing, setSyncing] = useState(false);
  useEffect(() => { const t = setTimeout(() => { setF((p) => ({ ...p, search: q })); setPage(0); }, 350); return () => clearTimeout(t); }, [q]);
  const list = useFetch<{ total: number; items: Review[] }>("/reviews", { ...f, limit: PAGE, offset: page * PAGE });
  // Per-state totals for the filter tabs. Cheap: limit=1 returns only the count.
  const cNone = useFetch<{ total: number }>("/reviews", { reply_state: "none", location_id: f.location_id, limit: 1 });
  const cDraft = useFetch<{ total: number }>("/reviews", { reply_state: "draft", location_id: f.location_id, limit: 1 });
  const cFail = useFetch<{ total: number }>("/reviews", { reply_state: "failed", location_id: f.location_id, limit: 1 });
  const refresh = useCallback(() => { void list.reload(); void cNone.reload(); void cDraft.reload(); void cFail.reload(); }, [list, cNone, cDraft, cFail]);
  const counts: Record<string, number | undefined> = { none: cNone.data?.total, draft: cDraft.data?.total, failed: cFail.data?.total };
  const connected = google.data?.connections.some((c) => c.status === "active");
  const items = list.data?.items ?? [];

  // On desktop, open something: the first review that needs attention, else the newest. Never leave the detail pane empty.
  useEffect(() => {
    if (seg || !items.length || typeof window === "undefined" || !window.matchMedia("(min-width: 768px)").matches) return;
    router.replace(`/gbp/reviews/${(items.find((i) => i.reply_state !== "published") ?? items[0]).id}`);
  }, [seg, items, router]);

  async function sync() {
    setSyncing(true);
    try { const r = await api<{ result: string }>("/google/sync", { method: "POST" }); toast(r.result === "queued" ? "Sync started. New reviews will appear shortly." : "Reviews synced."); setTimeout(refresh, 1500); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setSyncing(false); }
  }
  const setFilter = (k: "location_id" | "rating") => (e: React.ChangeEvent<HTMLSelectElement>) => { setF({ ...f, [k]: e.target.value }); setPage(0); };
  const ctx = useMemo(() => ({ refresh }), [refresh]);
  const filtered = Object.values({ ...f }).some(Boolean);

  return (
    <ReviewsCtx.Provider value={ctx}>
      <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
        <div><p className="eyebrow mb-1">Reputation</p><h1 className="text-xl font-bold sm:text-[22px]">Reviews</h1></div>
        {isAdmin && connected && <Button variant="secondary" size="sm" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={syncing} onClick={() => void sync()}>Sync now</Button>}
      </div>
      <div className="grid overflow-hidden rounded-panel border border-ink-100 bg-white md:h-[calc(100dvh-14rem)] md:min-h-[480px] md:grid-cols-[320px_minmax(0,1fr)] lg:h-[calc(100dvh-9.25rem)] lg:min-h-[520px] lg:grid-cols-[372px_minmax(0,1fr)]">
        <section aria-label="Review list" className={clsx("flex min-h-0 flex-col border-ink-100 md:border-r", seg ? "hidden md:flex" : "flex")}>
          <div className="space-y-2 border-b border-ink-100 p-3">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden />
              <input aria-label="Search reviews" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search text or name" className="min-h-11 w-full rounded-lg border border-ink-300 pl-8 pr-3 text-base sm:min-h-8 sm:text-sm" />
            </div>
            <div className="flex flex-wrap gap-x-0.5 gap-y-1" role="tablist" aria-label="Reply status">
              {STATES.map(([v, l]) => {
                const n = counts[v];
                const on = f.reply_state === v;
                return (
                  <button key={v} role="tab" aria-selected={on} onClick={() => { setF({ ...f, reply_state: v }); setPage(0); }}
                    className={clsx("inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-md px-2 text-[13px] font-medium transition-colors sm:min-h-7", on ? "bg-ink text-white" : "text-ink-700 hover:bg-ink-100/70")}>
                    {l}{n !== undefined && n > 0 && <span className={clsx("num rounded px-1 text-[11px] font-semibold", on ? "bg-white/20" : v === "failed" ? "bg-red-50 text-red-700" : v === "none" ? "bg-amber-50 text-amber-800" : "bg-ink-100 text-ink-700")}>{n}</span>}
                  </button>
                );
              })}
            </div>
            <div className="grid grid-cols-2 gap-2">
              <FilterSelect label="Location" value={f.location_id} onChange={setFilter("location_id")}><option value="">All locations</option>{locs.data?.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</FilterSelect>
              <FilterSelect label="Star rating" value={f.rating} onChange={setFilter("rating")}><option value="">Any rating</option>{[5, 4, 3, 2, 1].map((n) => <option key={n} value={n}>{n} stars</option>)}</FilterSelect>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {list.error && <p role="alert" className="p-4 text-sm text-red-700">{list.error}</p>}
            {list.loading && !list.data ? <div className="space-y-2 p-3">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-20" />)}</div>
              : items.length === 0 ? (
                <div className="p-4 text-sm">
                  <p className="font-semibold">{filtered ? "No reviews match these filters" : "No reviews synced yet"}</p>
                  <p className="mt-1 text-ink-500">{filtered ? "Try clearing a filter." : connected ? "New reviews appear here after each sync." : "Reviews sync once a Google Business Profile is connected. Until then, customers who use your card post their review directly on Google."}</p>
                  {!filtered && !connected && <LinkButton href="/gbp/locations" size="sm" variant="secondary" className="mt-3">Google connection</LinkButton>}
                </div>
              ) : (
                <ul role="list">
                  {items.map((r) => {
                    const st = REPLY_STATE[r.reply_state];
                    const sensitive = r.sensitive_reasons.length > 0 && r.reply_state !== "published";
                    const on = seg === r.id;
                    return (
                      <li key={r.id} className="border-b border-ink-100 last:border-b-0">
                        <Link href={`/gbp/reviews/${r.id}`} aria-current={on ? "true" : undefined}
                          className={clsx("relative grid gap-1 py-3 pl-4 pr-3 transition-colors", on ? "bg-brand-50/70" : sensitive ? "bg-red-50/40 hover:bg-red-50/70" : "hover:bg-ink-50/70")}>
                          <span aria-hidden className={clsx("absolute inset-y-0 left-0 w-[3px]", on ? "bg-brand-600" : sensitive ? "bg-red-600" : st.bar)} />
                          <div className="flex items-center justify-between gap-2">
                            <span className="flex min-w-0 items-center gap-2"><Stars rating={r.rating} size={13} /><span className="truncate text-sm font-semibold">{r.reviewer_name ?? "Google user"}</span></span>
                            <span className="shrink-0 text-xs text-ink-500">{timeAgo(r.review_created_at)}</span>
                          </div>
                          <p className="line-clamp-2 text-[13px] text-ink-700">{r.text || <span className="italic text-ink-400">Rating only, no written review</span>}</p>
                          <div className="flex flex-wrap items-center justify-between gap-x-3 text-xs text-ink-500">
                            <span className="truncate">{r.location_name}</span>
                            <span className="flex items-center gap-2">
                              {sensitive && <span className="inline-flex items-center gap-1 font-medium text-red-700"><AlertTriangle className="h-3 w-3" aria-hidden />Handle personally</span>}
                              <Status tone={st.tone} className="!text-xs">{st.label}</Status>
                            </span>
                          </div>
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              )}
          </div>

          {list.data && list.data.total > PAGE && (
            <div className="flex items-center justify-between border-t border-ink-100 px-3 py-2 text-xs text-ink-500">
              <Button variant="ghost" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</Button>
              <span className="num">{page * PAGE + 1}–{Math.min(list.data.total, (page + 1) * PAGE)} of {list.data.total}</span>
              <Button variant="ghost" size="sm" disabled={(page + 1) * PAGE >= list.data.total} onClick={() => setPage(page + 1)}>Next</Button>
            </div>
          )}
        </section>

        <section aria-label="Review detail" className={clsx("min-h-0 min-w-0 overflow-y-auto bg-white", seg ? "block" : "hidden md:block")}>{children}</section>
      </div>
    </ReviewsCtx.Provider>
  );
}
