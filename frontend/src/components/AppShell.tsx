"use client";
import clsx from "clsx";
import {
  BarChart3, Building2, LayoutDashboard, Link2, LogOut, MapPin, Menu, QrCode, Settings, ShieldCheck, Star, Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Logo } from "./ui/Brand";
import { Modal } from "./ui/Modal";
import { Spinner } from "./ui/Card";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/reviews", label: "Reviews", icon: Star },
  { href: "/cards", label: "QR/NFC cards", icon: QrCode },
  { href: "/cards/analytics", label: "Card analytics", icon: BarChart3 },
  { href: "/locations", label: "Locations", icon: MapPin },
  { href: "/google", label: "Google connection", icon: Link2 },
  { href: "/settings", label: "Business settings", icon: Settings },
  { href: "/staff", label: "Staff", icon: Users },
];
const BOTTOM = ["/dashboard", "/reviews", "/cards", "/locations"];

function isActive(path: string, href: string) {
  if (href === "/cards" || href === "/admin") return path === href;
  return path === href || path.startsWith(href + "/");
}

export function AppShell({ children }: { children: ReactNode }) {
  const { me, tenant, loading, logout, refresh } = useAuth();
  const path = usePathname();
  const router = useRouter();
  const [more, setMore] = useState(false);

  // FlowHQ platform admins may use /admin without owning a business.
  const adminOnly = !!me?.user.is_platform_admin && path.startsWith("/admin") && !tenant?.onboarding_completed;

  useEffect(() => {
    if (loading) return;
    if (!me) router.replace("/login");
    else if (!adminOnly && (!tenant || !tenant.onboarding_completed)) router.replace("/onboarding");
  }, [loading, me, tenant, router, adminOnly]);

  useEffect(() => setMore(false), [path]);

  if (loading || !me || (!adminOnly && (!tenant || !tenant.onboarding_completed))) return <div className="grid min-h-dvh place-items-center"><Spinner /></div>;

  const ADMIN_NAV = [{ href: "/admin", label: "Platform admin", icon: ShieldCheck }, { href: "/admin/cards", label: "Card inventory", icon: QrCode }];
  const items = adminOnly ? ADMIN_NAV : me.user.is_platform_admin ? [...NAV, { href: "/admin", label: "Platform admin", icon: ShieldCheck }] : NAV;
  const tenantName = tenant?.name ?? "FlowHQ platform admin";
  const nav = (cls: string, close?: boolean) => items.map((n) => (
    <Link key={n.href} href={n.href} aria-current={isActive(path, n.href) ? "page" : undefined}
      className={clsx("tap flex items-center gap-3 rounded-xl px-3 text-[15px] font-semibold transition-colors", cls,
        isActive(path, n.href) ? "bg-brand-50 text-brand-700" : "text-ink-700 hover:bg-ink-50")}>
      <n.icon className="h-5 w-5 shrink-0" aria-hidden />{n.label}
    </Link>
  ));

  const switchTenant = async (id: string) => { await api("/auth/select-tenant", { method: "POST", params: { tenant_id: id } }); await refresh(); router.refresh(); };

  return (
    <div className="min-h-dvh bg-ink-50/60">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-ink-100 bg-white px-3 py-5 lg:flex">
        <div className="px-2 pb-5"><Logo href="/dashboard" /></div>
        {me.memberships.length > 1 && tenant ? (
          <select aria-label="Switch business" value={tenant.id} onChange={(e) => void switchTenant(e.target.value)} className="mx-1 mb-4 min-h-11 rounded-xl border border-ink-200 bg-white px-3 text-sm font-semibold">
            {me.memberships.map((m) => <option key={m.tenant.id} value={m.tenant.id}>{m.tenant.name}</option>)}
          </select>
        ) : (
          <div className="mx-1 mb-4 flex items-center gap-2 rounded-xl bg-ink-50 px-3 py-2.5 text-sm font-semibold"><Building2 className="h-4 w-4 text-ink-500" aria-hidden /><span className="truncate">{tenantName}</span></div>
        )}
        <nav aria-label="Main" className="flex-1 space-y-1 overflow-y-auto">{nav("")}</nav>
        <div className="mt-3 border-t border-ink-100 pt-3">
          <p className="truncate px-3 text-xs text-ink-500">{me.user.email}</p>
          <button onClick={() => void logout()} className="tap mt-1 flex w-full items-center gap-3 rounded-xl px-3 text-[15px] font-semibold text-ink-700 hover:bg-ink-50"><LogOut className="h-5 w-5" aria-hidden />Log out</button>
        </div>
      </aside>

      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-ink-100 bg-white/90 px-4 py-2.5 backdrop-blur lg:hidden">
        <Logo href="/dashboard" tagline={false} />
        <span className="max-w-[45%] truncate text-sm font-semibold text-ink-700">{tenantName}</span>
      </header>

      <main className="lg:pl-64"><div className="mx-auto w-full max-w-6xl px-4 pb-28 pt-6 sm:px-6 lg:pb-12 lg:pt-8">{children}</div></main>

      <nav aria-label="Primary" className={clsx("fixed inset-x-0 bottom-0 z-30 grid", adminOnly ? "grid-cols-2" : "grid-cols-5", "border-t border-ink-100 bg-white pb-[env(safe-area-inset-bottom)] lg:hidden")}>
        {(adminOnly ? ADMIN_NAV : NAV).filter((n) => adminOnly || BOTTOM.includes(n.href)).map((n) => (
          <Link key={n.href} href={n.href} aria-current={isActive(path, n.href) ? "page" : undefined}
            className={clsx("flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-semibold", isActive(path, n.href) ? "text-brand-700" : "text-ink-500")}>
            <n.icon className="h-5 w-5" aria-hidden />{n.label.replace("QR/NFC cards", "Cards")}
          </Link>
        ))}
        {!adminOnly && <button onClick={() => setMore(true)} className="flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-semibold text-ink-500"><Menu className="h-5 w-5" aria-hidden />More</button>}
      </nav>

      <Modal open={more} onClose={() => setMore(false)} title="Menu">
        <nav aria-label="All pages" className="space-y-1">{nav("")}</nav>
        <button onClick={() => void logout()} className="tap mt-3 flex w-full items-center gap-3 rounded-xl px-3 text-[15px] font-semibold text-red-700 hover:bg-red-50"><LogOut className="h-5 w-5" aria-hidden />Log out</button>
      </Modal>
    </div>
  );
}
