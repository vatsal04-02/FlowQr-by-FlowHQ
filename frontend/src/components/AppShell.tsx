"use client";
import clsx from "clsx";
import {
  BarChart3, Building2, CreditCard, LayoutDashboard, Link2, LogOut, MapPin, Menu, QrCode, ScanLine, Settings, ShieldCheck, Star, Store, Users,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { SubscriptionInfo } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { Logo } from "./ui/Brand";
import { LinkButton } from "./ui/Button";
import { Alert, Spinner } from "./ui/Card";
import { Modal } from "./ui/Modal";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { href: "/reviews", label: "Reviews", icon: Star },
  { href: "/analytics", label: "Analytics", icon: BarChart3 },
  { href: "/cards", label: "QR/NFC cards", icon: QrCode },
  { href: "/cards/analytics", label: "Card analytics", icon: ScanLine },
  { href: "/locations", label: "Locations", icon: MapPin },
  { href: "/google", label: "Google connection", icon: Link2 },
  { href: "/profile", label: "Google profile", icon: Store },
  { href: "/subscription", label: "Subscription", icon: CreditCard },
  { href: "/staff", label: "Staff", icon: Users },
  { href: "/settings", label: "Settings", icon: Settings },
];
const BOTTOM = ["/dashboard", "/reviews", "/analytics", "/cards"];

function isActive(path: string, href: string) {
  if (href === "/cards") return path === "/cards";
  return path === href || path.startsWith(href + "/");
}

function Banners() {
  const { me, refresh } = useAuth();
  const path = usePathname();
  const sub = useFetch<SubscriptionInfo>("/billing/subscription");
  const [sent, setSent] = useState<string | null>(null);
  const s = sub.data;
  return (
    <div className="mb-5 space-y-3 empty:hidden">
      {me && !me.user.email_verified_at && (
        <Alert tone="warning" title="Verify your email" action={
          <button className="tap rounded-xl border border-amber-300 bg-white px-3 text-sm font-semibold text-amber-900 hover:bg-amber-100" onClick={async () => {
            try { const r = await api<{ email_sent: boolean; detail: string }>("/auth/resend-verification", { method: "POST" }); setSent(r.email_sent ? "Verification email sent. Check your inbox." : r.detail); void refresh(); } catch (e) { setSent(errorMessage(e)); }
          }}>Resend email</button>}>
          {sent ?? "Confirm your email to invite staff, connect Google and manage billing."}
        </Alert>
      )}
      {s && !path.startsWith("/subscription") && !path.startsWith("/payments") && (
        !s.active ? <Alert tone="error" title="Subscription inactive" action={<LinkButton href="/subscription" size="sm">Choose a plan</LinkButton>}>Your data is safe and your cards keep working, but editing, AI and sync are paused.</Alert>
        : s.status === "past_due" ? <Alert tone="warning" title="Payment failed" action={<LinkButton href="/subscription" size="sm" variant="secondary">Review billing</LinkButton>}>We couldn&rsquo;t charge your payment method. Access continues for now.</Alert>
        : s.status === "trialing" && (s.trial_days_left ?? 99) <= 5 ? <Alert tone="info" title={`${s.trial_days_left} days left in your free trial`} action={<LinkButton href="/subscription" size="sm">Choose a plan</LinkButton>}>Pick a plan to keep reviews, replies and AI running.</Alert>
        : null
      )}
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const { me, tenant, loading, logout, refresh } = useAuth();
  const path = usePathname();
  const router = useRouter();
  const [more, setMore] = useState(false);

  useEffect(() => {
    if (loading) return;
    if (!me) router.replace("/login");
    else if (!tenant || !tenant.onboarding_completed) router.replace(me.user.is_platform_admin && !tenant ? "/admin" : "/onboarding");
  }, [loading, me, tenant, router]);
  useEffect(() => setMore(false), [path]);

  if (loading || !me || !tenant || !tenant.onboarding_completed) return <div className="grid min-h-dvh place-items-center"><Spinner /></div>;

  if (tenant.suspended_at) {
    return (
      <div className="grid min-h-dvh place-items-center bg-ink-50 px-5"><div className="max-w-md text-center">
        <Logo className="mb-6" /><h1 className="text-2xl font-semibold">This account is suspended</h1>
        <p className="mt-2 text-ink-500">{tenant.suspension_reason ?? "Please contact FlowQR support."} Your QR/NFC cards are paused. Your data is retained.</p>
        <button onClick={() => void logout()} className="tap mt-6 rounded-xl border border-ink-200 bg-white px-5 font-semibold">Log out</button>
      </div></div>
    );
  }

  const items = me.user.is_platform_admin ? [...NAV, { href: "/admin", label: "Platform admin", icon: ShieldCheck }] : NAV;
  const nav = (cls: string) => items.map((n) => (
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
        {me.memberships.length > 1 ? (
          <select aria-label="Switch business" value={tenant.id} onChange={(e) => void switchTenant(e.target.value)} className="mx-1 mb-4 min-h-11 rounded-xl border border-ink-200 bg-white px-3 text-sm font-semibold">
            {me.memberships.map((m) => <option key={m.tenant.id} value={m.tenant.id}>{m.tenant.name}</option>)}
          </select>
        ) : (
          <div className="mx-1 mb-4 flex items-center gap-2 rounded-xl bg-ink-50 px-3 py-2.5 text-sm font-semibold"><Building2 className="h-4 w-4 text-ink-500" aria-hidden /><span className="truncate">{tenant.name}</span></div>
        )}
        <nav aria-label="Main" className="flex-1 space-y-0.5 overflow-y-auto">{nav("")}</nav>
        <div className="mt-3 border-t border-ink-100 pt-3">
          <p className="truncate px-3 text-xs text-ink-500">{me.user.email}</p>
          <button onClick={() => void logout()} className="tap mt-1 flex w-full items-center gap-3 rounded-xl px-3 text-[15px] font-semibold text-ink-700 hover:bg-ink-50"><LogOut className="h-5 w-5" aria-hidden />Log out</button>
        </div>
      </aside>

      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-ink-100 bg-white/90 px-4 py-2.5 backdrop-blur lg:hidden">
        <Logo href="/dashboard" tagline={false} />
        <span className="max-w-[45%] truncate text-sm font-semibold text-ink-700">{tenant.name}</span>
      </header>

      <main className="lg:pl-64"><div className="mx-auto w-full max-w-6xl px-4 pb-28 pt-6 sm:px-6 lg:pb-12 lg:pt-8"><Banners />{children}</div></main>

      <nav aria-label="Primary" className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-ink-100 bg-white pb-[env(safe-area-inset-bottom)] lg:hidden">
        {NAV.filter((n) => BOTTOM.includes(n.href)).map((n) => (
          <Link key={n.href} href={n.href} aria-current={isActive(path, n.href) ? "page" : undefined}
            className={clsx("flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-semibold", isActive(path, n.href) ? "text-brand-700" : "text-ink-500")}>
            <n.icon className="h-5 w-5" aria-hidden />{n.label.replace("QR/NFC cards", "Cards")}
          </Link>
        ))}
        <button onClick={() => setMore(true)} className="flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px] font-semibold text-ink-500"><Menu className="h-5 w-5" aria-hidden />More</button>
      </nav>

      <Modal open={more} onClose={() => setMore(false)} title="Menu">
        <nav aria-label="All pages" className="space-y-1">{nav("")}</nav>
        <button onClick={() => void logout()} className="tap mt-3 flex w-full items-center gap-3 rounded-xl px-3 text-[15px] font-semibold text-red-700 hover:bg-red-50"><LogOut className="h-5 w-5" aria-hidden />Log out</button>
      </Modal>
    </div>
  );
}
