"use client";
import { useEffect, useState } from "react";
import { api } from "./api";

export interface Counts { tasks: number; approvals: number }
const TTL = 60_000;
// One answer per business, kept for a minute: moving between pages never asks again, and switching business never shows the other one's numbers.
const cache = new Map<string, { at: number; data: Counts }>();

/**
 * The two sidebar badges, from the read-only GET /agent/counts (it never plans or writes). Refreshed about once a minute while the tab is visible. `null` until the first answer, and
 * `null` for good when the API says no (plan without the assistant, or a role that cannot see it): a badge is never guessed.
 */
export function useCounts(tenantId: string | undefined): Counts | null {
  const [data, setData] = useState<Counts | null>(() => (tenantId ? cache.get(tenantId)?.data ?? null : null));
  useEffect(() => {
    if (!tenantId) { setData(null); return; }
    let live = true, stop = false;
    const hit = cache.get(tenantId);
    setData(hit?.data ?? null);
    const load = async () => {
      const c = cache.get(tenantId);
      if (c && Date.now() - c.at < TTL) return;
      try {
        const d = await api<Counts>("/agent/counts");
        cache.set(tenantId, { at: Date.now(), data: d });
        if (live) setData(d);
      } catch { stop = true; if (live) setData(null); }
    };
    void load();
    const t = window.setInterval(() => { if (!stop && document.visibilityState === "visible") void load(); }, TTL);
    return () => { live = false; window.clearInterval(t); };
  }, [tenantId]);
  return data;
}

/** What the badge on a sidebar or bottom-bar destination says, or null for no badge. Only AI has one: the tasks and approvals waiting for the owner. */
export function badgeFor(destId: string, c: Counts | null): number | null {
  if (!c || destId !== "ai") return null;
  const n = c.tasks + c.approvals;
  return n > 0 ? n : null;
}
export function childBadge(href: string, c: Counts | null): number | null {
  if (!c) return null;
  const n = href === "/ai/tasks" ? c.tasks + c.approvals : 0;   // the "To review" page holds tasks, approvals and changes
  return n > 0 ? n : null;
}
