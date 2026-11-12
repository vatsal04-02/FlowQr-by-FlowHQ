"use client";
import clsx from "clsx";
import { ChevronDown, ChevronsUpDown, LogOut, Menu, ShieldCheck } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { LocationScopeProvider, useLocationScope } from "@/lib/location-scope";
import { isEntryActive, locate, NAV, TAB_HREFS, type NavGroup } from "@/lib/nav";
import type { SubscriptionInfo } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { Logo } from "./ui/Brand";
import { LinkButton } from "./ui/Button";
import { Alert, Spinner } from "./ui/Card";
import { Modal } from "./ui/Modal";

const ADMIN_GROUP: NavGroup = { id: "platform", title: "Platform", icon: ShieldCheck, href: "/admin", items: [] };

function Crumbs({ path }: { path: string }) {
  const l = locate(path);
  if (!l) return null;
  const crumbs = [{ label: l.group.title, href: l.group.items[0]?.href ?? l.group.href }, ...(l.item ? [{ label: l.item.label, href: l.item.href }] : [])];
  return (
    <nav aria-label="Breadcrumb" className="min-w-0">
      <ol className="flex flex-wrap items-center gap-x-1.5 text-[13px] text-ink-500">
        {crumbs.map((c, n) => (
          <li key={c.label} className="flex items-center gap-1.5">
            {n > 0 && <span aria-hidden>/</span>}
            {n < crumbs.length - 1 || l.detail ? <Link href={c.href ?? "#"} className="hover:text-ink hover:underline">{c.label}</Link> : <span aria-current="page" className="font-medium text-ink-700">{c.label}</span>}
          </li>))}
        {l.detail && <li className="flex items-center gap-1.5"><span aria-hidden>/</span><span aria-current="page" className="font-medium text-ink-700">Details</span></li>}
      </ol>
    </nav>
  );
}

function LocationPicker() {
  const { locations, locationId, setLocationId } = useLocationScope();
  if (locations.length < 2) return null; // one location: nothing to choose
  return (
    <label className="flex items-center gap-2 text-[13px] text-ink-500">
      <span className="hidden sm:inline">Location</span>
      <select aria-label="Location" value={locationId ?? ""} onChange={(e) => setLocationId(e.target.value || undefined)}
        className="min-h-9 max-w-[220px] rounded-lg border border-ink-200 bg-white px-2 text-sm font-medium text-ink-700">
        <option value="">All locations</option>
        {locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
      </select>
    </label>
  );
}

const OPEN_KEY = "flowqr:nav-open";

function Banners({ s }: { s: SubscriptionInfo | null }) {
  const { me, refresh, role } = useAuth();
  const path = usePathname();
  const del = useFetch<{ requested: boolean; scheduled_for: string | null }>(role === "owner" ? "/account/deletion" : null).data;
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
      {del?.requested && <Alert tone="warning" title="This business is scheduled for deletion" action={<LinkButton href="/settings#data" size="sm" variant="secondary">Review</LinkButton>}>Everything works until {del.scheduled_for ? new Date(del.scheduled_for).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "the scheduled date"}; you can cancel in Settings.</Alert>}
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
  const [openIds, setOpenIds] = useState<string[]>([]);
  const sub = useFetch<SubscriptionInfo>("/billing/subscription");

  useEffect(() => {
    if (loading) return;
    if (!me) router.replace("/login");
    else if (!tenant || !tenant.onboarding_completed) router.replace(me.user.is_platform_admin && !tenant ? "/admin" : "/onboarding");
  }, [loading, me, tenant, router]);
  useEffect(() => setMore(false), [path]);
  useEffect(() => { try { const v = JSON.parse(localStorage.getItem(OPEN_KEY) ?? "[]"); if (Array.isArray(v)) setOpenIds(v); } catch { /* ignore */ } }, []);
  const here = locate(path);
  // the group you are in is always open; the others stay as you left them
  const isOpen = (g: NavGroup) => g.id === here?.group.id || openIds.includes(g.id);
  const toggle = (g: NavGroup) => setOpenIds((cur) => {
    const next = cur.includes(g.id) ? cur.filter((x) => x !== g.id) : [...cur, g.id];
    try { localStorage.setItem(OPEN_KEY, JSON.stringify(next)); } catch { /* ignore */ }
    return next;
  });

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
  const groups = me.user.is_platform_admin ? [...NAV, ADMIN_GROUP] : NAV;
  const tabs = TAB_HREFS.map((h) => groups.flatMap((g) => (g.items.length ? g.items : [{ href: g.href!, label: g.title, icon: g.icon }])).find((n) => n.href === h)).filter((n): n is NonNullable<typeof n> => !!n);

  const linkCls = (on: boolean) => clsx("flex min-h-11 items-center gap-2.5 rounded-lg px-2.5 text-sm transition-colors lg:min-h-8", on ? "bg-brand-50 font-semibold text-brand-700" : "font-medium text-ink-700 hover:bg-ink-50");
  const nav = (label: string) => (
    <ul className="space-y-px" aria-label={label}>
      {groups.map((g) => {
        const open = isOpen(g);
        const inGroup = here?.group.id === g.id;
        if (!g.items.length) {
          const on = isEntryActive(path, g.href!) || path === g.href || path.startsWith(g.href + "/");
          return <li key={g.id}><Link href={g.href!} aria-current={on ? "page" : undefined} className={linkCls(on)}><g.icon className={clsx("h-[17px] w-[17px] shrink-0", on ? "text-brand-600" : "text-ink-400")} strokeWidth={1.8} aria-hidden />{g.title}</Link></li>;
        }
        return (
          <li key={g.id}>
            <button type="button" onClick={() => toggle(g)} aria-expanded={open} aria-controls={`nav-${label}-${g.id}`}
              className={clsx("flex min-h-11 w-full items-center gap-2.5 rounded-lg px-2.5 text-left text-sm font-medium transition-colors hover:bg-ink-50 lg:min-h-8", inGroup ? "text-ink" : "text-ink-700")}>
              <g.icon className={clsx("h-[17px] w-[17px] shrink-0", inGroup ? "text-brand-600" : "text-ink-400")} strokeWidth={1.8} aria-hidden />
              <span className="flex-1">{g.title}</span>
              <ChevronDown className={clsx("h-3.5 w-3.5 text-ink-400 transition-transform", open && "rotate-180")} aria-hidden />
            </button>
            {open && (
              <ul id={`nav-${label}-${g.id}`} className="ml-[18px] mt-px space-y-px border-l border-ink-100 pl-2">
                {g.items.map((n) => {
                  const on = isEntryActive(path, n.href);
                  return <li key={n.href}><Link href={n.href} aria-current={on ? "page" : undefined} className={clsx(linkCls(on), "min-h-10 lg:min-h-[30px]")}>{n.label}</Link></li>;
                })}
              </ul>)}
          </li>
        );
      })}
    </ul>
  );
  const switchTenant = async (id: string) => { await api("/auth/select-tenant", { method: "POST", params: { tenant_id: id } }); await refresh(); router.refresh(); };

  return (
    <LocationScopeProvider>
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
        <nav aria-label="Main" className="flex-1 overflow-y-auto pr-0.5 [scrollbar-width:thin]">{nav("Main pages")}</nav>
        <div className="mt-3 border-t border-ink-100 pt-3">
          <p className="truncate px-2.5 text-xs text-ink-500">{me.user.email}</p>
          <button onClick={() => void logout()} className="mt-1 flex min-h-8 w-full items-center gap-2.5 rounded-lg px-2.5 text-sm font-medium text-ink-700 transition-colors hover:bg-ink-50"><LogOut className="h-[17px] w-[17px] text-ink-400" strokeWidth={1.8} aria-hidden />Log out</button>
        </div>
      </aside>

      <header className="sticky top-0 z-20 flex items-center justify-between border-b border-ink-100 bg-white px-4 py-2 lg:hidden">
        <Logo href="/dashboard" tagline={false} />
        <span className="max-w-[48%] truncate text-sm font-medium text-ink-700">{tenant.name}</span>
      </header>

      <main className="lg:pl-[232px]"><div className="mx-auto w-full max-w-[1180px] px-4 pb-24 pt-5 sm:px-6 lg:pb-10 lg:pt-6">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-x-4 gap-y-2"><Crumbs path={path} /><LocationPicker /></div>
        <Banners s={s} />{children}</div></main>

      <nav aria-label="Primary" className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-ink-100 bg-white pb-[env(safe-area-inset-bottom)] lg:hidden">
        {tabs.map((n) => {
          const on = isEntryActive(path, n.href);
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
        <nav aria-label="All pages">{nav("Menu pages")}</nav>
        <button onClick={() => void logout()} className="tap mt-5 flex w-full items-center gap-2.5 rounded-lg px-2.5 text-sm font-medium text-red-700 hover:bg-red-50"><LogOut className="h-[17px] w-[17px]" aria-hidden />Log out</button>
      </Modal>
    </div>
    </LocationScopeProvider>
  );
}