"use client";
import clsx from "clsx";
import { ArrowDown, ArrowUp, Info, Loader2, Minus, Plus, RefreshCw, Trash2 } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
import { Alert, Skeleton } from "@/components/ui/Card";
import { Input } from "@/components/ui/Form";
import { useToast } from "@/components/ui/Toast";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { timeAgo } from "@/lib/format";
import { useFetch } from "@/lib/use-api";

interface Result { name: string | null; rating: number | null; reviews: number | null; is_you: boolean; position: number | null }
interface Check { id: string; status: "ok" | "error"; rank: number | null; results_seen: number | null; error: string | null; checked_at: string; source: string; top_results: Result[] }
interface Kw { id: string; keyword: string; latest: Check | null; previous_rank: number | null; change: number | null }
interface Overview {
  configured: boolean; max_keywords: number; note: string; usage: { used: number; cap: number; resets_on: string };
  location: { title: string | null; has_place_id: boolean }; keywords: Kw[];
}

const rankTone = (r: number | null) => r === null ? "bg-surface-2 text-muted" : r <= 3 ? "bg-pos-tint text-pos" : r <= 10 ? "bg-warn-tint text-warn" : "bg-neg-tint text-neg";

function Change({ k }: { k: Kw }) {
  if (k.change === null) return <span className="text-xs text-muted">{k.latest?.status === "ok" ? "First measurement" : ""}</span>;
  if (k.change === 0) return <span className="inline-flex items-center gap-1 text-xs text-muted"><Minus className="h-3.5 w-3.5" aria-hidden />No change</span>;
  const up = k.change > 0;
  return (
    <span className={clsx("inline-flex items-center gap-1 text-xs font-semibold", up ? "text-pos" : "text-neg")}>
      {up ? <ArrowUp className="h-3.5 w-3.5" aria-hidden /> : <ArrowDown className="h-3.5 w-3.5" aria-hidden />}
      {up ? "Up" : "Down"} {Math.abs(k.change)} since last check
    </span>
  );
}

/**
 * GBP Manager › Local ranking. Real positions from Google's Places API (New): for each search term, where this business appears among the
 * first 20 results around its location, with the date measured. "Not in top 20" is shown as exactly that, and a failed check is shown as
 * failed. Only owners and admins can add terms or run checks (each check uses part of a monthly allowance of billed Google calls).
 */
export function LocalRank({ gid }: { gid: string }) {
  const { isAdmin } = useAuth();
  const toast = useToast();
  const ov = useFetch<Overview>(`/gbp/${gid}/rank`);
  const [word, setWord] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  async function add() {
    if (!word.trim()) return;
    setBusy("add");
    try { await api(`/gbp/${gid}/rank/keywords`, { method: "POST", body: { keyword: word } }); setWord(""); toast("Search term added. Run a check to measure it."); await ov.reload(); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); }
  }
  async function remove(k: Kw) {
    setBusy(k.id);
    try { await api(`/gbp/${gid}/rank/keywords/${k.id}`, { method: "DELETE" }); toast("Removed."); await ov.reload(); }
    catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); }
  }
  async function check(id?: string) {
    setBusy(id ?? "all");
    try {
      const r = await api<{ checked: number; failed: number; stopped: string | null }>(`/gbp/${gid}/rank/check`, { method: "POST", body: id ? { keyword_id: id } : {} });
      toast(r.stopped ? `Checked ${r.checked}. ${r.stopped}` : r.failed ? `Checked ${r.checked}, ${r.failed} failed. See the reason below.` : `Checked ${r.checked} search term${r.checked === 1 ? "" : "s"}.`, r.failed ? "error" : undefined);
      await ov.reload();
    } catch (e) { toast(errorMessage(e), "error"); } finally { setBusy(null); }
  }

  if (ov.error) return <Alert tone="error" title="Couldn't load local ranking">{ov.error}</Alert>;
  if (!ov.data) return <Skeleton className="h-48" />;
  const d = ov.data;
  const left = Math.max(0, d.usage.cap - d.usage.used);
  const canRun = isAdmin && d.configured && d.location.has_place_id;

  return (
    <div className="space-y-6">
      {!d.configured && <Alert tone="warning" title="Local ranking isn't switched on for this server">The server needs a Google Places API (New) key (<code>RANK_PROVIDER=google_places</code> and <code>RANK_PROVIDER_KEY</code>). Until then nothing is measured and no numbers are shown.</Alert>}
      {d.configured && !d.location.has_place_id && <Alert tone="warning" title="This location has no Google place ID yet">Sync the location from Google on the Locations page, then come back.</Alert>}

      <section className="panel p-5 sm:p-6" aria-labelledby="rk-h">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 id="rk-h" className="text-[15px] font-semibold">Manage words</h2>
            <p className="mt-0.5 text-[13px] text-muted">Up to {d.max_keywords}. Checked weekly.</p>
          </div>
          <div className="text-right text-xs text-muted" aria-label="Monthly checks">
            <div className="text-[13px] font-semibold text-ink">{left}/{d.usage.cap} checks</div>
            <div>Resets {new Date(d.usage.resets_on).toLocaleDateString(undefined, { day: "numeric", month: "short" })}</div>
          </div>
        </div>

        {isAdmin && (
          <form className="mt-4 flex max-w-xl flex-col gap-2 sm:flex-row sm:items-end" onSubmit={(e) => { e.preventDefault(); void add(); }}>
            <div className="flex-1"><Input label="Add a search term" value={word} onChange={(e) => setWord(e.target.value)} maxLength={80} placeholder="e.g. physiotherapist near me" disabled={d.keywords.length >= d.max_keywords} /></div>
            <Button type="submit" icon={<Plus className="h-4 w-4" aria-hidden />} loading={busy === "add"} disabled={!word.trim() || d.keywords.length >= d.max_keywords}>Add</Button>
          </form>
        )}

        {d.keywords.length === 0 ? (
          <p className="mt-6 rounded-tile bg-surface-2 p-5 text-sm text-muted">No search terms yet. {isAdmin ? "Add one above, then run a check." : "An owner or admin adds the terms to track."}</p>
        ) : (
          <>
            <div className="mt-5 flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold">Search terms ({d.keywords.length})</h3>
              {isAdmin && <Button size="sm" variant="secondary" onClick={() => void check()} loading={busy === "all"} disabled={!canRun || left === 0} icon={<RefreshCw className="h-4 w-4" aria-hidden />}>Check all now</Button>}
            </div>
            <ul className="mt-3 divide-y divide-line rounded-tile border border-line">
              {d.keywords.map((k) => {
                const c = k.latest;
                return (
                  <li key={k.id} className="p-4">
                    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                      <div className={clsx("grid h-12 w-16 shrink-0 place-items-center rounded-tile text-center", c?.status === "ok" ? rankTone(c.rank) : "bg-surface-2 text-muted")}
                        aria-label={!c ? "Not checked yet" : c.status === "error" ? "Check failed" : c.rank ? `Position ${c.rank}` : "Not in the first 20 results"}>
                        {!c ? <span className="text-xs">–</span> : c.status === "error" ? <span className="text-xs font-semibold">Failed</span> : c.rank ? <span className="text-xl font-semibold tabular-nums">#{c.rank}</span> : <span className="px-1 text-[11px] font-semibold leading-tight">Not in top 20</span>}
                      </div>
                      <div className="min-w-0 flex-1">
                        <p data-words="skip" className="truncate font-semibold">{k.keyword}</p>
                        <p className="text-xs text-muted">{c ? `Checked ${timeAgo(c.checked_at)}` : "Not checked yet"}</p>
                        <Change k={k} />
                      </div>
                      <div className="flex items-center gap-1">
                        {c?.status === "ok" && c.top_results.length > 0 && <Button size="sm" variant="ghost" onClick={() => setOpen(open === k.id ? null : k.id)} aria-expanded={open === k.id}>Above you</Button>}
                        {isAdmin && <Button size="sm" variant="secondary" onClick={() => void check(k.id)} loading={busy === k.id} disabled={!canRun || left === 0} aria-label={`Check ${k.keyword} now`} icon={<RefreshCw className="h-4 w-4" aria-hidden />}>Check</Button>}
                        {isAdmin && <Button size="sm" variant="ghost" onClick={() => void remove(k)} disabled={busy === k.id} aria-label={`Remove ${k.keyword}`}>{busy === k.id ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Trash2 className="h-4 w-4" aria-hidden />}</Button>}
                      </div>
                    </div>
                    {c?.status === "error" && <p className="mt-2 rounded-tile bg-neg-tint p-2.5 text-sm text-neg">Last check failed: {c.error}</p>}
                    {open === k.id && c && (
                      <ol className="mt-3 divide-y divide-line rounded-tile bg-surface-2 text-sm">
                        {c.top_results.map((p, i) => (
                          <li key={i} className={clsx("flex items-center gap-3 px-3 py-2", p.is_you && "bg-accent-tint font-semibold")}>
                            <span className="w-7 shrink-0 tabular-nums text-muted">{p.position ?? i + 1}</span>
                            <span className="min-w-0 flex-1 truncate">{p.name}{p.is_you ? " (you)" : ""}</span>
                            <span className="shrink-0 text-xs text-muted">{p.rating ? `${p.rating.toFixed(1)}★` : ""}{p.reviews ? ` · ${p.reviews} reviews` : ""}</span>
                          </li>
                        ))}
                      </ol>
                    )}
                  </li>
                );
              })}
            </ul>
          </>
        )}
        <p className="mt-4 flex items-start gap-2 text-xs text-muted"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />Measured from Google Places. Maps can order results differently.</p>
      </section>
    </div>
  );
}
