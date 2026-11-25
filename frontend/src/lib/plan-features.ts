"use client";
import { useEffect, useState } from "react";
import type { PlanFeatures } from "./nav-features";

/**
 * The plan features of the selected business, for the menus. Live data wins; the last known answer for the same business is kept in this browser so the menu is right from the first
 * paint of a later visit instead of showing everything for a moment. It only decides what is SHOWN: the server enforces every feature itself.
 */
export function usePlanFeatures(tenantId: string | undefined, live: string[] | undefined): PlanFeatures {
  const key = tenantId ? `flowqr:plan-features:${tenantId}` : null;
  const [cached, setCached] = useState<string[] | null>(null);
  useEffect(() => {
    if (!key) { setCached(null); return; }
    try { const v = localStorage.getItem(key); setCached(v ? (JSON.parse(v) as string[]) : null); } catch { setCached(null); }
  }, [key]);
  useEffect(() => {
    if (key && live) { try { localStorage.setItem(key, JSON.stringify(live)); } catch { /* private mode */ } }
  }, [key, live]);
  const list = live ?? cached;
  return list ? new Set(list) : null;
}
