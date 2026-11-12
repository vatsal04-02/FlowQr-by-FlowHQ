"use client";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import type { Location } from "@/lib/types";
import { useFetch } from "@/lib/use-api";

interface Scope {
  /** the locations the signed-in person may see (the server already hides the others) */
  locations: Location[];
  /** selected location id, or undefined for "all my locations" */
  locationId: string | undefined;
  setLocationId: (id: string | undefined) => void;
  loading: boolean;
}
const Ctx = createContext<Scope | null>(null);
const key = (tenantId: string) => `flowqr:location:${tenantId}`;

/** One location selector for the whole app. The choice is a convenience filter, never a permission: the API enforces access. */
export function LocationScopeProvider({ children }: { children: ReactNode }) {
  const { tenant } = useAuth();
  const { data, loading } = useFetch<Location[]>(tenant ? "/locations" : null);
  const [id, setId] = useState<string | undefined>(undefined);
  const locations = useMemo(() => (data ?? []).filter((l) => l.is_active), [data]);

  useEffect(() => {
    if (!tenant) return;
    try { const v = localStorage.getItem(key(tenant.id)); setId(v || undefined); } catch { setId(undefined); }
  }, [tenant]);
  // a remembered location that no longer exists (or is no longer visible to this person) falls back to "all"
  const valid = id && locations.some((l) => l.id === id) ? id : undefined;
  const setLocationId = useCallback((v: string | undefined) => {
    setId(v);
    if (tenant) { try { v ? localStorage.setItem(key(tenant.id), v) : localStorage.removeItem(key(tenant.id)); } catch { /* private mode */ } }
  }, [tenant]);

  const value = useMemo(() => ({ locations, locationId: valid, setLocationId, loading }), [locations, valid, setLocationId, loading]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useLocationScope(): Scope {
  const v = useContext(Ctx);
  if (!v) throw new Error("useLocationScope must be used inside LocationScopeProvider");
  return v;
}
