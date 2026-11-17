"use client";
import clsx from "clsx";
import { BellGlyph } from "@/components/icons/Nav";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { useDismiss, type Notice } from "./parts";
import { tbBtn } from "./TopBar";

interface Item { id: string; kind: string; tone: "info" | "warn" | "bad"; title: string; body: string; href: string; at: string; unread: boolean }
interface Feed { items: Item[]; unread: number }

const POLL_MS = 60_000;

/**
 * The bell (PRD §6.5): account notices from the shell (subscription, email, deletion) plus `GET /notifications` (new and flagged reviews,
 * failed replies and posts, sync errors, trial ending), polled every minute while the tab is visible. Opening it marks everything read.
 */
export function BellMenu({ notices }: { notices: Notice[] }) {
  const [open, setOpen] = useState(false);
  const [feed, setFeed] = useState<Feed | null>(null);
  const wrap = useRef<HTMLDivElement>(null), btn = useRef<HTMLButtonElement>(null);
  useDismiss(wrap, open, () => setOpen(false), btn);

  const load = useCallback(async () => { try { setFeed(await api<Feed>("/notifications")); } catch { /* the bell is a convenience: stay quiet */ } }, []);
  useEffect(() => {
    void load();
    const t = window.setInterval(() => { if (document.visibilityState === "visible") void load(); }, POLL_MS);
    return () => window.clearInterval(t);
  }, [load]);

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && feed && feed.unread > 0) {
      void api("/notifications/seen", { method: "POST" }).then(() => setFeed((f) => f && { items: f.items.map((i) => ({ ...i, unread: false })), unread: 0 })).catch(() => undefined);
    }
  };
  const unread = (feed?.unread ?? 0) + notices.length;
  const items = feed?.items.slice(0, 12) ?? [];

  return (
    <div ref={wrap} className="relative">
      <button ref={btn} type="button" aria-label={unread ? `Notifications, ${unread} new` : "Notifications"} aria-expanded={open} aria-haspopup="dialog" onClick={toggle} className={tbBtn}>
        <BellGlyph className="h-5 w-5" strokeWidth={1.6} />
        {unread > 0 && <span aria-hidden className="absolute right-[9px] top-[8px] h-2 w-2 rounded-full bg-accent ring-2 ring-surface"><span className="absolute -inset-1 rounded-full border-[1.5px] border-accent opacity-0 motion-safe:animate-[fq-ping_1.6s_ease-out_3]" /></span>}
      </button>
      {open && (
        <div role="dialog" aria-label="Notifications" className="fq-enter fixed inset-x-3 top-[68px] z-50 rounded-card bg-surface p-2 text-sm shadow-lift ring-1 ring-line sm:absolute sm:inset-x-auto sm:right-0 sm:top-[calc(100%+10px)] sm:w-[380px]">
          <div className="flex items-center justify-between px-3 pb-1 pt-2.5"><p className="text-xs font-medium text-muted">Notifications</p>
            <Link href="/settings/notifications" onClick={() => setOpen(false)} className="text-xs font-semibold text-accent-ink hover:underline">Email settings</Link></div>
          {notices.length === 0 && items.length === 0 ? (
            <p className="px-3 pb-3 pt-1 text-muted">You&rsquo;re all caught up. New reviews, flagged reviews and sync problems show up here.</p>
          ) : (
            <ul className="max-h-[calc(100dvh-200px)] overflow-y-auto overscroll-contain sm:max-h-[60vh]">
              {notices.map((n) => (
                <li key={n.id}><Link href={n.href} onClick={() => setOpen(false)} className="flex gap-3 rounded-tile p-3 transition-colors hover:bg-surface-2">
                  <Dot tone={n.tone} />
                  <span className="min-w-0"><span className="block font-semibold">{n.title}</span><span className="block text-[13px] text-muted">{n.body}</span>
                    <span className="mt-1 block text-[13px] font-semibold text-accent-ink">{n.cta}</span></span>
                </Link></li>
              ))}
              {items.map((i) => (
                <li key={i.id}><Link href={i.href} onClick={() => setOpen(false)} className={clsx("flex gap-3 rounded-tile p-3 transition-colors hover:bg-surface-2", i.unread && "bg-accent-tint/60")}>
                  <Dot tone={i.tone} />
                  <span className="min-w-0 flex-1"><span className="block font-semibold">{i.title}</span><span className="line-clamp-2 block text-[13px] text-muted">{i.body}</span>
                    <span className="mt-1 block text-xs text-muted">{timeAgo(i.at)}{i.unread && <span className="sr-only"> (new)</span>}</span></span>
                </Link></li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

const Dot = ({ tone }: { tone: "info" | "warn" | "bad" }) => <span aria-hidden className={clsx("mt-1.5 h-2 w-2 shrink-0 rounded-full", tone === "bad" ? "bg-neg" : tone === "warn" ? "bg-warn" : "bg-accent")} />;
