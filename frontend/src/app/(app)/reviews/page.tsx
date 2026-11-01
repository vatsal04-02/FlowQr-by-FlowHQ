"use client";
import { AlertTriangle, MessageSquareReply, RefreshCw, Search } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Button, LinkButton } from "@/components/ui/Button";
import { Alert, Badge, Card, EmptyState, PageHeader, Skeleton, Stars } from "@/components/ui/Card";
import { FilterSelect } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/format";
import type { Location, Review } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

const STATE_LABEL: Record<Review["reply_state"], [string, "gray" | "blue" | "amber" | "green" | "red"]> = {
  none: ["Needs reply", "amber"], draft: ["Draft ready", "blue"], approved: ["Approved", "blue"], published: ["Replied", "green"], failed: ["Publish failed", "red"],
};
const PAGE = 20;

export default function ReviewsInbox() {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const locs = useFetch<Location[]>("/locations");
  const [f, setF] = useState({ location_id: "", rating: "", reply_state: "", search: "" });
  const [q, setQ] = useState("");
  const [page, setPage] = useState(0);
  const [syncing, setSyncing] = useState(false);
  useEffect(() => { const t = setTimeout(() => { setF((p) => ({ ...p, search: q })); setPage(0); }, 350); return () => clearTimeout(t); }, [q]);
  const { data, error, loading, reload } = useFetch<{ total: number; items: Review[] }>("/reviews", { ...f, limit: PAGE, offset: page * PAGE });
  const google = useFetch<{ configured: boolean; connections: { status: string }[] }>("/google/status");

  async function sync() {
    setSyncing(true);
    try { const r = await api<{ result: string }>("/google/sync", { method: "POST" }); toast(r.result === "queued" ? "Sync started. New reviews will appear shortly." : "Reviews synced."); setTimeout(reload, 1500); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setSyncing(false); }
  }
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLSelectElement>) => { setF({ ...f, [k]: e.target.value }); setPage(0); };
  const connected = google.data?.connections.some((c) => c.status === "active");

  return (
    <>
      <PageHeader title="Reviews" subtitle="Every Google review in one inbox. Replies are always approved by a person." actions={isAdmin && connected ? <Button variant="secondary" icon={<RefreshCw className="h-4 w-4" />} loading={syncing} onClick={() => void sync()}>Sync now</Button> : undefined} />
      <Card pad={false} className="mb-4 p-3 sm:p-4">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[200px] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden />
            <input aria-label="Search reviews" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search text or name" className="min-h-11 w-full rounded-xl border border-ink-200 pl-9 pr-3 text-sm sm:min-h-10" />
          </div>
          <FilterSelect label="Location" value={f.location_id} onChange={set("location_id")}><option value="">All locations</option>{locs.data?.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}</FilterSelect>
          <FilterSelect label="Star rating" value={f.rating} onChange={set("rating")}><option value="">All ratings</option>{[5, 4, 3, 2, 1].map((n) => <option key={n} value={n}>{n} stars</option>)}</FilterSelect>
          <FilterSelect label="Reply status" value={f.reply_state} onChange={set("reply_state")}>
            <option value="">All statuses</option><option value="none">Needs reply</option><option value="draft">Draft ready</option><option value="approved">Approved</option><option value="failed">Publish failed</option><option value="published">Replied</option>
          </FilterSelect>
        </div>
      </Card>

      {error && <Alert tone="error">{error}</Alert>}
      {loading && !data ? <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-28" />)}</div> :
        data && data.items.length === 0 ? (
          <EmptyState icon={<MessageSquareReply className="h-6 w-6" />} title={Object.values(f).some(Boolean) ? "No reviews match these filters" : "No reviews yet"}
            action={!connected && !Object.values(f).some(Boolean) ? <LinkButton href="/google">Connect Google to sync reviews</LinkButton> : undefined}>
            {connected ? "New reviews appear here after each sync." : "Reviews sync once your Google Business Profile is connected. Until then, share your card so customers can post reviews directly on Google."}
          </EmptyState>
        ) : (
          <ul className="space-y-3">
            {data?.items.map((r) => {
              const [label, tone] = STATE_LABEL[r.reply_state];
              return (
                <li key={r.id}>
                  <Link href={`/reviews/${r.id}`} className="block rounded-2xl border border-ink-100 bg-white p-4 shadow-card transition-shadow hover:shadow-pop sm:p-5">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-3"><Stars rating={r.rating} /><span className="font-semibold">{r.reviewer_name ?? "Google user"}</span></div>
                      <div className="flex flex-wrap items-center gap-2">
                        {r.sensitive_reasons.length > 0 && r.reply_state !== "published" && <Badge tone="red"><AlertTriangle className="h-3 w-3" aria-hidden />Handle personally</Badge>}
                        <Badge tone={tone}>{label}</Badge>
                      </div>
                    </div>
                    <p className="mt-2 line-clamp-3 text-ink-700">{r.text || <span className="italic text-ink-400">Rating only, no written review</span>}</p>
                    <p className="mt-2 text-xs text-ink-500">{r.location_name} · {fmtDate(r.review_created_at)}{r.update_count > 0 && " · edited by reviewer"}</p>
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      {data && data.total > PAGE && (
        <div className="mt-5 flex items-center justify-between">
          <Button variant="secondary" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</Button>
          <span className="text-sm text-ink-500">{page * PAGE + 1}–{Math.min(data.total, (page + 1) * PAGE)} of {data.total}</span>
          <Button variant="secondary" size="sm" disabled={(page + 1) * PAGE >= data.total} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      )}
    </>
  );
}
