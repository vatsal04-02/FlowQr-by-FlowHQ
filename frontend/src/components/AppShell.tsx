"use client";
import clsx from "clsx";
import { Check, ChevronDown, CreditCard, LogOut, ShieldCheck, Users } from "lucide-react";
import { MotionConfig } from "motion/react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { LocationScopeProvider, useLocationScope } from "@/lib/location-scope";
import { navFor } from "@/lib/nav";
import { useAppChrome } from "@/lib/theme";
import type { SubscriptionInfo } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { CommandPalette } from "./shell/CommandPalette";
import { BellMenu } from "./shell/Bell";
import { BottomNav, MoreSheet } from "./shell/BottomNav";
import { HelpMenu, PopoverButton, SubNav, ThemeToggle, type Notice } from "./shell/parts";
import { Sidebar, SIDEBAR_W } from "./shell/Sidebar";
import { StatusStrip } from "./shell/StatusStrip";
import { Crumbs, SearchPill, StatusDot, SyncChip, TrialPill, useGoogleHeader } from "./shell/TopBar";
import { LogoMark } from "./ui/Brand";
import { Spinner } from "./ui/Card";

/** Which location the page shows. Hidden with one location (nothing to choose). It is a convenience filter: the API enforces access. */
function LocationPicker({ className }: { className?: string }) {
  const { locations, locationId, setLocationId } = useLocationScope();
  if (locations.length < 2) return null;
  return (
    <label className={clsx("flex items-center gap-2 text-[13px] text-muted", className)}>
      <span className="sr-only">Location</span>
      <select aria-label="Show data for location" value={locationId ?? ""} onChange={(e) => setLocationId(e.target.value || undefined)}
        className="min-h-11 max-w-[200px] rounded-xl bg-surface px-3 text-sm font-medium text-ink ring-1 ring-ink-100 sm:min-h-10">
        <option value="">All locations</option>
        {locations.map((l) => <option key={l.id} value={l.id}>{l.name}</option>)}
      </select>
    </label>
  );
}

const initials = (name: string | undefined, email: string) => {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  return (parts.length ? parts.slice(0, 2).map((p) => p[0]) : [email[0]]).join("").toUpperCase();
};

/**
 * The logged-in app frame (docs/DESIGN.md, "Shell"). One navigation system: a bottom bar on phones, one left sidebar on tablet and desktop. The top bar holds only the
 * business, the location filter, search, notifications and the account. Every page keeps its own URL; this only decides how it is reached.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { me, tenant, role, loading, logout, refresh } = useAuth();
  const path = usePathname();
  const router = useRouter();
  const [palette, setPalette] = useState(false);
  const [more, setMore] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  useAppChrome();
  const sub = useFetch<SubscriptionInfo>(tenant ? "/billing/subscription" : null);
  const deletion = useFetch<{ requested: boolean; scheduled_for: string | null }>(role === "owner" ? "/account/deletion" : null).data;
  const legal = useFetch<{ support_email: string | null }>("/legal/info").data;
  const dests = useMemo(() => navFor(role), [role]);
  const google = useGoogleHeader(!!tenant && !!tenant.onboarding_completed);
  // the bar gains a soft shadow once the page has scrolled under it
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 6);
    on(); window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);

  // The sidebar remembers how the person left it; with no saved choice it starts open on a desktop and as an icon rail on a tablet.
  useEffect(() => {
    try { const v = localStorage.getItem("flowqr:sidebar"); setCollapsed(v ? v === "collapsed" : window.innerWidth < 1100); } catch { setCollapsed(window.innerWidth < 1100); }
  }, []);
  const toggleSidebar = () => setCollapsed((c) => { try { localStorage.setItem("flowqr:sidebar", c ? "expanded" : "collapsed"); } catch { /* private mode */ } return !c; });

  useEffect(() => {
    if (loading) return;
    if (!me) router.replace("/login");
    else if (!tenant || !tenant.onboarding_completed) router.replace(me.user.is_platform_admin && !tenant ? "/admin" : "/onboarding");
  }, [loading, me, tenant, router]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((o) => !o); } };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  useEffect(() => { setPalette(false); setMore(false); }, [path]);

  const s = sub.data;
  const notices = useMemo<Notice[]>(() => {
    const out: Notice[] = [];
    if (s && !s.active) out.push({ id: "inactive", tone: "bad", title: "Plan inactive", body: "Your data is safe and your cards keep working. Editing, AI and sync are paused until you choose a plan.", href: "/settings/billing", cta: "Choose a plan" });
    else if (s?.status === "past_due") out.push({ id: "past-due", tone: "bad", title: "Payment failed", body: "We couldn't charge your payment method.", href: "/settings/billing", cta: "Review billing" });
    // trial ending comes from GET /notifications (the bell), so it is not repeated here
    if (me && !me.user.email_verified_at) out.push({ id: "verify", tone: "warn", title: "Verify your email", body: "Needed to invite staff, connect Google and manage billing.", href: "/settings/account", cta: "Open your account" });
    if (deletion?.requested) out.push({ id: "deletion", tone: "warn", title: "This business is scheduled for deletion", body: "You can cancel it in Settings until the date.", href: "/settings#data", cta: "Review" });
    return out;
  }, [s, me, deletion]);

  if (loading || !me || !tenant || !tenant.onboarding_completed) return <div className="grid min-h-dvh place-items-center"><Spinner /></div>;

  if (tenant.suspended_at) {
    return (
      <div className="grid min-h-dvh place-items-center bg-canvas px-5"><div className="max-w-md text-center">
        <span className="hero-grad mx-auto mb-6 grid h-14 w-14 place-items-center rounded-full"><LogoMark size={26} variant="onAccent" /></span>
        <h1 className="text-2xl font-semibold">This account is suspended</h1>
        <p className="mt-2 text-muted">{tenant.suspension_reason ?? "Please contact FlowQR support."} Your QR/NFC cards are paused. Your data is retained.</p>
        <button onClick={() => void logout()} className="tap mt-6 rounded-full bg-ink-solid px-6 font-semibold text-ink-on">Log out</button>
      </div></div>
    );
  }

  const switchTenant = async (id: string) => { await api("/auth/select-tenant", { method: "POST", params: { tenant_id: id } }); await refresh(); router.refresh(); };
  const name = me.user.full_name?.trim() || me.user.email;
  const avatar = <span aria-hidden className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-ink-solid text-[13px] font-semibold text-ink-on">{initials(me.user.full_name, me.user.email)}</span>;
  const help = (inRail?: boolean) => <HelpMenu supportEmail={legal?.support_email} onSearch={() => setPalette(true)} align={inRail ? "left" : "right"} inRail={inRail} />;

  const business = (
    <PopoverButton label="Business menu" align="left" className="min-w-0" buttonClass="group flex min-h-11 min-w-0 max-w-[calc(100vw-232px)] items-center gap-2.5 rounded-[14px] bg-surface py-1 pl-1.5 pr-2.5 text-left shadow-pill ring-1 ring-line transition-[transform,box-shadow] duration-200 ease-spring hover:-translate-y-px hover:shadow-lift active:scale-[.98] motion-reduce:transition-none motion-reduce:hover:transform-none sm:max-w-[340px]"
      icon={<>
        <span className="relative shrink-0">
          <span aria-hidden className="grid h-9 w-9 place-items-center rounded-full bg-accent text-[14px] font-semibold text-on-accent shadow-[inset_0_1px_0_rgba(255,255,255,.3)]">{tenant.name.slice(0, 1).toUpperCase()}</span>
          {google.line?.tone === "ok" && <span aria-hidden className="absolute -bottom-px -right-px h-[11px] w-[11px] rounded-full bg-pos ring-2 ring-surface" />}
        </span>
        <span className="min-w-0">
          <span className="block truncate text-[14.5px] font-semibold leading-[1.2]">{tenant.name}</span>
          {google.line && <span className="hidden items-center gap-1.5 text-xs leading-[1.3] text-muted min-[860px]:flex"><StatusDot tone={google.line.tone} /><span className="truncate">{google.line.label}</span></span>}
        </span>
        <ChevronDown className="h-4 w-4 shrink-0 text-ink-400" aria-hidden /></>}>
      {(close) => (
        <div className="p-1">
          <p className="px-3 pb-1 pt-2 text-xs font-medium text-muted">{me.memberships.length > 1 ? "Your businesses" : "Your business"}</p>
          {me.memberships.map((m) => (
            <button key={m.tenant.id} type="button" onClick={() => { close(); if (m.tenant.id !== tenant.id) void switchTenant(m.tenant.id); }}
              className="flex min-h-11 w-full items-center justify-between gap-3 rounded-xl px-3 text-left font-medium hover:bg-surface-2">
              <span className="truncate">{m.tenant.name}</span>{m.tenant.id === tenant.id && <Check className="h-4 w-4 shrink-0 text-accent-ink" aria-label="Current" />}
            </button>
          ))}
          <div className="mt-1 border-t border-ink-100 pt-1">
            {google.line && <Link href={google.line.href} onClick={close} className="flex min-h-11 items-center gap-2 rounded-xl px-3 font-medium hover:bg-surface-2"><StatusDot tone={google.line.tone} className="!h-2 !w-2" />{google.line.label}</Link>}
            <Link href="/settings" onClick={close} className="flex min-h-11 items-center rounded-xl px-3 font-medium hover:bg-surface-2">Business settings</Link>
          </div>
        </div>
      )}
    </PopoverButton>
  );

  const canBill = role === "owner" || role === "admin";
  const rowCls = "flex min-h-11 items-center gap-2.5 rounded-xl px-3 font-medium hover:bg-surface-2";
  const account = (
    <PopoverButton label="Account menu" align="right"
      buttonClass="grid h-11 w-11 place-items-center rounded-full transition-transform duration-300 ease-spring hover:scale-105 hover:-rotate-3 motion-reduce:transition-none motion-reduce:hover:transform-none"
      icon={<span className="grid h-11 w-11 place-items-center rounded-full bg-[conic-gradient(from_200deg,rgb(var(--c-accent)),rgb(var(--c-tone-amber)),rgb(var(--c-tone-teal)),rgb(var(--c-tone-sky)),rgb(var(--c-accent)))] shadow-pill"><span className="rounded-full ring-2 ring-canvas">{avatar}</span></span>}>
      {(close) => (
        <div className="p-1">
          <div className="flex items-center gap-3 px-3 pb-3 pt-2">
            {avatar}
            <div className="min-w-0 flex-1"><p className="truncate font-semibold">{name}</p><p className="truncate text-[13px] text-muted">{me.user.email}</p></div>
            {role && <span className="shrink-0 rounded-full bg-accent-tint px-2.5 py-0.5 text-xs font-semibold capitalize text-accent-ink">{role}</span>}
          </div>
          <div className="border-t border-ink-100 py-1">
            <Link href="/settings/account" onClick={close} className={rowCls}>Your account</Link>
            {canBill && <Link href="/settings/billing" onClick={close} className={rowCls}><CreditCard className="h-4 w-4 text-ink-500" aria-hidden />Plan and billing</Link>}
            <Link href="/settings/team" onClick={close} className={rowCls}><Users className="h-4 w-4 text-ink-500" aria-hidden />Team</Link>
            <Link href="/settings/appearance" onClick={close} className={rowCls}>Appearance</Link>
            {me.user.is_platform_admin && <Link href="/admin" onClick={close} className={rowCls}><ShieldCheck className="h-4 w-4" aria-hidden />Platform admin</Link>}
            <div className="flex min-h-11 items-center justify-between gap-2 px-3"><span className="font-medium">Theme</span><ThemeToggle small /></div>
            <button type="button" onClick={() => { close(); void logout(); }} className="flex min-h-11 w-full items-center gap-2 rounded-xl px-3 text-left font-medium text-neg hover:bg-neg-tint"><LogOut className="h-4 w-4" aria-hidden />Log out</button>
          </div>
        </div>
      )}
    </PopoverButton>
  );

  return (
    <MotionConfig reducedMotion="user">
    <LocationScopeProvider>
    <div className="min-h-dvh bg-canvas" style={{ ["--sb" as string]: `${collapsed ? SIDEBAR_W.rail : SIDEBAR_W.open}px` }}>
      <a href="#app-main" className="sr-only z-[60] rounded-lg bg-surface px-4 py-2 font-semibold focus:not-sr-only focus:fixed focus:left-3 focus:top-3">Skip to content</a>
      <Sidebar path={path} dests={dests} collapsed={collapsed} onToggle={toggleSidebar} help={help(true)} />
      <div className="transition-[padding] duration-200 ease-out motion-reduce:transition-none md:pl-[var(--sb)]">
        <header className={clsx("top-glass sticky top-0 z-30", scrolled && "scrolled")}>
          <div className="mx-auto flex h-[68px] w-full max-w-[1240px] items-center justify-between gap-2 px-3 sm:px-6 lg:px-8">
            <div className="flex min-w-0 items-center gap-1.5">
              <Link href="/overview" aria-label="FlowQR home" className="hero-grad grid h-9 w-9 shrink-0 place-items-center rounded-[10px] !shadow-none md:hidden"><LogoMark size={19} variant="onAccent" /></Link>
              {business}
              <Crumbs path={path} />
            </div>
            <div className="flex shrink-0 items-center gap-1.5 sm:gap-2">
              <LocationPicker className="hidden md:flex" />
              <SearchPill onOpen={() => setPalette(true)} />
              <SyncChip chip={google.chip} canSync={canBill} reload={google.reload} />
              {!notices.length && <TrialPill s={s ?? null} path={path} className="max-[1279px]:hidden" />}
              <BellMenu notices={notices} />
              {account}
            </div>
          </div>
        </header>

        <main id="app-main" tabIndex={-1} className="mx-auto w-full min-w-0 max-w-[1240px] px-4 pb-[calc(88px+env(safe-area-inset-bottom))] pt-5 outline-none sm:px-6 md:pb-12 lg:px-8">
          <StatusStrip notices={path.startsWith("/settings/billing") ? notices.filter((n) => !n.href.startsWith("/settings/billing")) : notices} />
          <div className="mb-3 flex flex-wrap items-center gap-2 empty:hidden">{!notices.length && <TrialPill s={s ?? null} path={path} className="min-[1280px]:hidden" />}<LocationPicker className="md:hidden" /></div>
          {/* with the sidebar open the pages of this destination are listed there, so the tab strip is only needed on a phone or when the sidebar is a rail */}
          <SubNav path={path} dests={dests} hidePrimaryOnWide={!collapsed} />
          {children}
        </main>
      </div>
      <BottomNav path={path} dests={dests} moreOpen={more} onMore={setMore} />
      <MoreSheet open={more} onClose={() => setMore(false)} role={role} onSearch={() => setPalette(true)} supportEmail={legal?.support_email} />
      <CommandPalette open={palette} onClose={() => setPalette(false)} dests={dests} />
    </div>
    </LocationScopeProvider>
    </MotionConfig>
  );
}
