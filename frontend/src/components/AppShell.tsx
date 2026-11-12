"use client";
import clsx from "clsx";
import {
  BarChart3, ChevronsUpDown, CreditCard, LayoutDashboard, Link2, LogOut, MapPin, Menu, Paintbrush, Palette, QrCode, ScanLine, Settings, ShieldCheck, SlidersHorizontal,
  Sparkles, Star, Store, TrendingUp, Users,
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

type NavItem = { href: string; label: string; icon: typeof Star };
const GROUPS: { title: string; items: NavItem[] }[] = [
  { title: "Reputation", items: [
    { href: "/dashboard", label: "Overview", icon: LayoutDashboard },
    { href: "/reviews", label: "Reviews", icon: Star },
    { href: "/analytics", label: "Analytics", icon: BarChart3 },
  ] },
  { title: "Cards", items: [
    { href: "/cards", label: "Cards", icon: QrCode },
    { href: "/cards/analytics", label: "Card analytics", icon: ScanLine },
    { href: "/qr", label: "QR design & export", icon: Paintbrush },
    { href: "/locations", label: "Locations", icon: MapPin },
  ] },
  { title: "Review Growth", items: [
    { href: "/review-growth", label: "Overview", icon: TrendingUp },
    { href: "/review-growth/campaigns", label: "QR campaigns", icon: QrCode },
    { href: "/review-growth/generator", label: "AI review generator", icon: Sparkles },
    { href: "/review-growth/customize", label: "Landing page", icon: Palette },
    { href: "/review-growth/analytics", label: "Analytics", icon: BarChart3 },
    { href: "/review-growth/settings", label: "Settings", icon: SlidersHorizontal },
  ] },
  { title: "Business", items: [
    { href: "/google", label: "Google connection", icon: Link2 },
    { href: "/profile", label: "Google profile", icon: Store },
    { href: "/subscription", label: "Subscription", icon: CreditCard },
    { href: "/staff", label: "Staff", icon: Users },
    { href: "/settings", label: "Settings", icon: Settings },
  ] },
];
const ADMIN_GROUP = { title: "Platform", items: [{ href: "/admin", label: "Platform admin", icon: ShieldCheck }] };
const TABS = ["/dashboard", "/reviews", "/cards", "/analytics"];

function isActive(path: string, href: string) {
  if (href === "/cards") return path === "/cards" || /^\/cards\/(?!analytics)/.test(path);
  if (href === "/review-growth") return path === href; // its sub-pages have their own nav items
  if (href === "/review-growth/campaigns") return path === href || path.startsWith(href + "/");
  return path === href || path.startsWith(href + "/");
}

function Banners({ s }: { s: SubscriptionInfo | null }) {
  const { me, refresh } = useAuth();
  const path = usePathname();
  const [sent, setSent] = useState<string | null>(null);
  return (
    <div className="mb-4 space-y-2 empty:hidden">
      {me && !me.user.email_verified_at && (
        <Alert tone="warning" title="Verify your email" action={
          <button className="tap rounded-lg border border-amber-300 bg-white px-3 text-sm font-medium text-amber-900 hover:bg-amber-100" onClick={async () => {
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
  const sub = useFetch<SubscriptionInfo>("/billing/subscription");

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
        <button onClick={() => void logout()} className="tap mt-6 rounded-lg border border-ink-200 bg-white px-5 font-medium">Log out</button>
      </div></div>
    );
  }

  const s = sub.data;
  const planLine = s ? (s.status === "trialing" ? `Trial · ${s.trial_days_left ?? 0} days left` : `${s.plan_name ?? "No plan"} plan`) : " ";
  const groups = me.user.is_platform_admin ? [...GROUPS, ADMIN_GROUP] : GROUPS;
  const tabs = GROUPS.flatMap((g) => g.items).filter((n) => TABS.includes(n.href)).sort((a, b) => TABS.indexOf(a.href) - TABS.indexOf(b.href));

  const nav = (label: string) => groups.map((g) => (
    <div key={g.title} role="group" aria-label={`${g.title} ${label}`} className="mt-5 first:mt-0">
      <p className="eyebrow px-2.5 pb-1.5 !text-[11px] text-ink-400">{g.title}</p>
      <div className="space-y-px">
        {g.items.map((n) => {
          const on = isActive(path, n.href);
          return (
            <Link key={n.href} href={n.href} aria-current={on ? "page" : undefined}
              className={clsx("flex min-h-11 items-center gap-2.5 rounded-lg px-2.5 text-sm transition-colors lg:min-h-8",
                on ? "bg-brand-50 font-semibold text-brand-700" : "font-medium text-ink-700 hover:bg-ink-50")}>
              <n.icon className={clsx("h-[17px] w-[17px] shrink-0", on ? "text-brand-600" : "text-ink-400")} strokeWidth={1.8} aria-hidden />{n.label}
            </Link>
          );
        })}
      </div>
    </div>
  ));
  const switchTenant = async (id: string) => { await api("/auth/select-tenant", { method: "POST", params: { tenant_id: id } }); await refresh(); router.refresh(); };

  return (
    <div className="min-h-dvh bg-ink-50">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[232px] flex-col border-r border-ink-100 bg-white px-3 py-4 lg:flex">
        <div className="px-1.5 pb-4"><Logo href="/dashboard" /></div>
        <div className="relative mb-4 rounded-lg border border-ink-100 bg-ink-50/60 px-2.5 py-2">
          <p className="truncate text-sm font-semibold">{tenant.name}</p>
          <p className="truncate text-xs text-ink-500">{planLine}</p>
          {me.memberships.length > 1 && (
            <>
              <ChevronsUpDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-400" aria-hidden />
              <select aria-label="Switch business" value={tenant.id} onChange={(e) => void switchTenant(e.target.value)} className="absolute inset-0 h-full w-full cursor-pointer opacity-0">
                {me.memberships.map((m) => <option key={m.tenant.id} value={m.tenant.id}>{m.tenant.name}</option>)}
              </select>
            </>
          )}
        </div>
        <nav aria-label="Main" className="flex-1 overflow-y-auto pr-0.5 [scrollbar-width:thin]">{nav("pages")}</nav>
        <div className="mt-3 border-t border-ink-100 pt-3">
          <p className="truncate px-2.5 text-xs text-ink-500">{me.user.email}</p>
          <button onClick={() => void logout()} className="mt-1 flex min-h-8 w-full items-center gap-2.5 rounded-lg px-2.5 text-sm font-medium text-ink-700 transition-colors hover:bg-ink-50"><LogOut className="h-[17px] w-[17px] text-ink-400" strokeWidth={1.8} aria-hidden />Log out</button>
        </div>
      </aside>

      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-ink-100 bg-white px-4 py-2 lg:hidden">
        <Logo href="/dashboard" tagline={false} />
        <span className="max-w-[48%] truncate text-sm font-medium text-ink-700">{tenant.name}</span>
      </header>

      <main className="lg:pl-[232px]"><div className="mx-auto w-full max-w-[1180px] px-4 pb-24 pt-5 sm:px-6 lg:pb-10 lg:pt-6"><Banners s={s} />{children}</div></main>

      <nav aria-label="Primary" className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-ink-100 bg-white pb-[env(safe-area-inset-bottom)] lg:hidden">
        {tabs.map((n) => {
          const on = isActive(path, n.href);
          return (
            <Link key={n.href} href={n.href} aria-current={on ? "page" : undefined}
              className={clsx("flex min-h-14 flex-col items-center justify-center gap-0.5 text-xs font-medium transition-colors", on ? "text-brand-600" : "text-ink-500")}>
              <n.icon className="h-5 w-5" strokeWidth={on ? 2.3 : 1.8} aria-hidden />{n.label}
            </Link>
          );
        })}
        <button onClick={() => setMore(true)} className="flex min-h-14 flex-col items-center justify-center gap-0.5 text-xs font-medium text-ink-500"><Menu className="h-5 w-5" strokeWidth={1.8} aria-hidden />More</button>
      </nav>

      <Modal open={more} onClose={() => setMore(false)} title="Menu">
        <nav aria-label="All pages">{nav("menu")}</nav>
        <button onClick={() => void logout()} className="tap mt-5 flex w-full items-center gap-2.5 rounded-lg px-2.5 text-sm font-medium text-red-700 hover:bg-red-50"><LogOut className="h-[17px] w-[17px]" aria-hidden />Log out</button>
      </Modal>
    </div>
  );
}
