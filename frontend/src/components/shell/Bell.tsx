"use client";
import clsx from "clsx";
import { Bell } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { iconBtn, useDismiss, type Notice } from "./parts";

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
      <button ref={btn} type="button" aria-label={unread ? `Notifications, ${unread} new` : "Notifications"} aria-expanded={open} aria-haspopup="dialog" onClick={toggle} className={iconBtn}>
        <Bell className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden />
        {unread > 0 && <span aria-hidden className="absolute right-[11px] top-[10px] h-2 w-2 rounded-full bg-accent ring-2 ring-surface" />}
      </button>
      {open && (
        <div role="dialog" aria-label="Notifications" className="fq-enter absolute right-0 top-[calc(100%+10px)] z-50 w-[min(92vw,380px)] rounded-card bg-surface p-2 text-sm shadow-lift">
          <div className="flex items-center justify-between px-3 pb-1 pt-2.5"><p className="text-xs font-medium text-muted">Notifications</p>
            <Link href="/settings/notifications" onClick={() => setOpen(false)} className="text-xs font-semibold text-accent-ink hover:underline">Email settings</Link></div>
          {notices.length === 0 && items.length === 0 ? (
            <p className="px-3 pb-3 pt-1 text-muted">You&rsquo;re all caught up. New reviews, flagged reviews and sync problems show up here.</p>
          ) : (
            <ul className="max-h-[60vh] overflow-y-auto">
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
