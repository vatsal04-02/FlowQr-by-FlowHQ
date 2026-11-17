"use client";
import clsx from "clsx";
import { ChevronRight, Clock, RefreshCw, Search } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { locate } from "@/lib/nav";
import { crumbParts, googleLine, showTrialChip, syncChip, type Tone } from "@/lib/shell-status";
import type { GoogleConnection, GoogleLocation, SubscriptionInfo } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

/** A raised square button for the top bar (bell, search on phones). Springs up on hover, presses down on tap. */
export const tbBtn = "relative grid h-10 w-10 shrink-0 place-items-center rounded-[12px] bg-surface text-ink shadow-pill ring-1 ring-line transition-[transform,box-shadow] duration-200 ease-spring hover:-translate-y-px hover:shadow-lift active:scale-95 motion-reduce:transition-none motion-reduce:hover:transform-none";

const DOT: Record<Tone, string> = { ok: "bg-pos", warn: "bg-warn", bad: "bg-neg", idle: "bg-ink-300" };

/** Re-render every minute so "13m ago" stays true while the page is open. */
function useMinute() {
  const [, set] = useState(0);
  useEffect(() => { const t = window.setInterval(() => set((n) => n + 1), 60_000); return () => window.clearInterval(t); }, []);
}

/**
 * What the top bar knows about Google: the connection (for the line under the business name) and the synced locations (for the sync chip). Two cheap reads that the API
 * already serves; nothing is assumed while they load or if the person's role may not read them.
 */
export function useGoogleHeader(enabled: boolean) {
  const status = useFetch<{ configured: boolean; connections: GoogleConnection[] }>(enabled ? "/google/status" : null);
  const active = status.data?.connections.find((c) => c.status === "active");
  const locs = useFetch<GoogleLocation[]>(active ? `/google/connections/${active.id}/locations` : null);
  const line = googleLine(status.data?.connections);
  const chip = syncChip(locs.data);
  const reloadStatus = status.reload, reloadLocs = locs.reload;
  const reload = useCallback(() => { reloadStatus(); reloadLocs(); }, [reloadStatus, reloadLocs]);
  return { line, chip, reload };
}

/** The sync chip: "Synced 13m ago". Owners and admins can press it to ask Google for new data now; staff just see the state. Icon only below 1000px. */
export function SyncChip({ chip, canSync, reload }: { chip: ReturnType<typeof syncChip>; canSync: boolean; reload: () => void }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  useMinute();
  if (!chip) return null;
  const text = note ?? (busy ? "Syncing…" : chip.kind === "ok" ? `Synced ${timeAgo(chip.lastSyncedAt)}` : chip.label);
  const detail = chip.kind === "ok" ? `Last synced ${timeAgo(chip.lastSyncedAt)}` : chip.kind === "waiting" ? "Waiting for the first sync from Google" : chip.lastSyncedAt ? `${chip.label}. Last good sync ${timeAgo(chip.lastSyncedAt)}` : chip.label;
  const tone = chip.tone === "ok" ? "text-pos" : chip.tone === "warn" ? "text-warn" : chip.tone === "bad" ? "text-neg" : "text-muted";
  const run = async () => {
    if (busy) return;
    setBusy(true); setNote(null);
    try {
      await api("/google/sync", { method: "POST" });
      // the sync runs in the background queue: look again shortly rather than claim it is done
      window.setTimeout(() => { reload(); setBusy(false); }, 4000);
    } catch (e) {
      setBusy(false); setNote(errorMessage(e)); window.setTimeout(() => setNote(null), 5000);
    }
  };
  const inner = <><RefreshCw className={clsx("h-4 w-4 shrink-0", busy && "fq-spin")} strokeWidth={1.75} aria-hidden /><span className="hidden min-[1000px]:inline">{text}</span></>;
  const cls = clsx("tb-chip max-[859px]:hidden max-[999px]:w-10 max-[999px]:justify-center max-[999px]:px-0", tone, !canSync && "pointer-events-none");
  return canSync
    ? <button type="button" onClick={() => void run()} aria-label={`${text}. Sync with Google now`} title={detail} aria-busy={busy} className={cls}>{inner}</button>
    : <span role="status" title={detail} aria-label={detail} className={cls}>{inner}</span>;
}

/** "5 days left · Choose a plan", only in the last five days of a trial. In the bar from 1280px (room for it beside an open sidebar); below that the same chip sits in the page (AppShell). */
export function TrialPill({ s, path, className }: { s: SubscriptionInfo | null | undefined; path: string; className?: string }) {
  if (!showTrialChip(s, path)) return null;
  const d = s?.trial_days_left ?? 0;
  return (
    <Link href="/settings/billing" className={clsx("tb-chip !text-accent-ink bg-accent-tint !shadow-none ring-1 ring-accent-edge/40", className)}>
      <Clock className="h-4 w-4 shrink-0" strokeWidth={1.75} aria-hidden />
      <span>{d === 0 ? "Trial ends today" : `${d} ${d === 1 ? "day" : "days"} left`}</span>
      <span className="-mr-1.5 rounded-lg bg-ink-solid px-2.5 py-1 text-xs font-semibold text-ink-on">Choose a plan</span>
    </Link>
  );
}

/** Where you are, from the same navigation file as the sidebar: "GBP › Profile › Photos". Only from 1480px so nothing else is squeezed. */
export function Crumbs({ path }: { path: string }) {
  const parts = crumbParts(locate(path));
  if (!parts.length) return null;
  return (
    <nav aria-label="Breadcrumb" className="ml-2 hidden h-6 min-w-0 items-center gap-1.5 border-l border-ink-200 pl-4 text-[13.5px] text-muted min-[1480px]:flex">
      {parts.map((p, i) => (
        <span key={p + i} className="flex items-center gap-1.5 whitespace-nowrap">
          {i > 0 && <ChevronRight className="h-3.5 w-3.5 text-ink-300" aria-hidden />}
          <span aria-current={i === parts.length - 1 ? "page" : undefined} className={i === parts.length - 1 ? "fq-enter font-semibold text-ink" : undefined}>{p}</span>
        </span>
      ))}
    </nav>
  );
}

/** "Search or jump to…  Ctrl K". A wide pill from 860px, a square icon button below. Opens the command palette. */
export function SearchPill({ onOpen }: { onOpen: () => void }) {
  const [mac, setMac] = useState(false);
  useEffect(() => { setMac(/Mac|iPhone|iPad/.test(navigator.platform)); }, []);
  return (
    <button type="button" aria-label="Search (Ctrl K)" onClick={onOpen}
      className={clsx(tbBtn, "min-[860px]:ml-1 min-[860px]:flex min-[860px]:h-10 min-[860px]:w-auto min-[860px]:min-w-[150px] min-[860px]:max-w-[300px] min-[860px]:flex-[0_1_300px] min-[860px]:items-center min-[860px]:justify-start min-[860px]:gap-2.5 min-[860px]:pl-3 min-[860px]:pr-2 min-[860px]:text-muted")}>
      <Search className="h-[18px] w-[18px] shrink-0" strokeWidth={1.75} aria-hidden />
      <span className="hidden min-w-0 flex-1 truncate text-left text-[13.5px] min-[860px]:block">Search or jump to…</span>
      <kbd className="hidden rounded-md bg-surface-2 px-1.5 py-0.5 font-sans text-[11.5px] text-muted ring-1 ring-line min-[860px]:block">{mac ? "⌘K" : "Ctrl K"}</kbd>
    </button>
  );
}

/** The small coloured dot on the business avatar and in front of the Google line. */
export const StatusDot = ({ tone, className }: { tone: Tone; className?: string }) => <span aria-hidden className={clsx("inline-block h-1.5 w-1.5 shrink-0 rounded-full", DOT[tone], className)} />;
