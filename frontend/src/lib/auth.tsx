"use client";
import { MARKETING_ROUTES } from "./site";
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api, ApiError } from "./api";
import type { Me, Role, Tenant } from "./types";

/**
 * WhatsApp is switched off in the app for everyone (owner decision 2026-11-27): no menu entry, no Settings row, no search result, and a typed /whatsapp address says it is not available.
 * Every WhatsApp screen already reads me.integrations.whatsapp_enabled, so forcing it off here removes all of them at once. To bring WhatsApp back, set this to false (the server switch
 * WHATSAPP_ENABLED still decides after that).
 */
const WHATSAPP_HIDDEN = true;
const withoutWhatsApp = (m: Me): Me => (WHATSAPP_HIDDEN ? { ...m, integrations: { ...m.integrations, whatsapp_enabled: false } } : m);

interface AuthState {
  me: Me | null;
  loading: boolean;
  tenant: Tenant | null;
  role: Role | null;
  isAdmin: boolean; // owner or admin
  refresh: () => Promise<Me | null>;
  logout: () => Promise<void>;
}

const Ctx = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();
  const pathname = usePathname();
  const isPublicCard = ["/c/", "/q/", "/n/", "/r/"].some((p) => pathname.startsWith(p)); // customers on a QR/NFC or campaign landing page never need the session
  // The public marketing pages never use the session either; skipping it avoids a 401 on every visit.
  const isMarketing = MARKETING_ROUTES.includes(pathname);

  const refresh = useCallback(async () => {
    try {
      const m = withoutWhatsApp(await api<Me>("/auth/me"));
      setMe(m);
      return m;
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) setMe(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { if (isPublicCard || isMarketing) { setLoading(false); return; } void refresh(); }, [refresh, isPublicCard, isMarketing]);

  const logout = useCallback(async () => {
    try { await api("/auth/logout", { method: "POST" }); } catch { /* already logged out */ }
    setMe(null);
    router.replace("/login");
  }, [router]);

  const value = useMemo<AuthState>(() => {
    const active = me?.memberships.find((m) => m.tenant.id === me.active_tenant_id) ?? me?.memberships[0] ?? null;
    return {
      me, loading, refresh, logout,
      tenant: active?.tenant ?? null, role: active?.role ?? null,
      isAdmin: active?.role === "owner" || active?.role === "admin",
    };
  }, [me, loading, refresh, logout]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useAuth must be used inside AuthProvider");
  return v;
}
