"use client";
import clsx from "clsx";
import { Check, ChevronDown, LogOut, Search, ShieldCheck } from "lucide-react";
import { MotionConfig } from "motion/react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { LocationScopeProvider, useLocationScope } from "@/lib/location-scope";
import { navFor } from "@/lib/nav";
import { useAppChrome } from "@/lib/theme";
import type { SubscriptionInfo } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { CommandPalette } from "./shell/CommandPalette";
import { BellMenu } from "./shell/Bell";
import { BottomNav, MoreSheet } from "./shell/BottomNav";
import { HelpMenu, iconBtn, PopoverButton, SubNav, ThemeToggle, type Notice } from "./shell/parts";
import { Sidebar, SIDEBAR_W } from "./shell/Sidebar";
import { LogoMark } from "./ui/Brand";
import { LinkButton } from "./ui/Button";
import { Alert, Spinner } from "./ui/Card";

/** The free trial, once and small: days left plus the one action. Only shown when the trial is nearly over. */
function TrialChip({ s }: { s: SubscriptionInfo | null }) {
  const path = usePathname();
  if (!s || s.status !== "trialing" || (s.trial_days_left ?? 99) > 5 || path.startsWith("/settings/billing") || path.startsWith("/settings/billing/payments")) return null;
  const d = s.trial_days_left ?? 0;
  return (
    <Link href="/settings/billing" className="inline-flex min-h-10 items-center gap-2 rounded-full bg-accent-tint px-4 text-[13px] font-semibold text-accent-ink transition-colors hover:bg-brand-100">
      <span aria-hidden className="h-2 w-2 rounded-full bg-accent" />{d === 0 ? "Trial ends today" : `${d} ${d === 1 ? "day" : "days"} left in trial`}<span className="underline underline-offset-2">Choose a plan</span>
    </Link>
  );
}

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

function Banners({ s, deletion }: { s: SubscriptionInfo | null; deletion: { requested: boolean; scheduled_for: string | null } | null }) {
  const { me, refresh } = useAuth();
  const path = usePathname();
  const [sent, setSent] = useState<string | null>(null);
  return (
    <div className="mb-4 space-y-3 empty:hidden">
      {me && !me.user.email_verified_at && (
        <Alert tone="warning" title="Verify your email" action={
          <button className="tap rounded-full bg-white px-4 text-sm font-semibold text-ink hover:bg-ink-50" onClick={async () => {
            try { const r = await api<{ email_sent: boolean; detail: string }>("/auth/resend-verification", { method: "POST" }); setSent(r.email_sent ? "Verification email sent. Check your inbox." : r.detail); void refresh(); } catch (e) { setSent(errorMessage(e)); }
          }}>Resend email</button>}>
          {sent ?? "Confirm your email to invite staff, connect Google and manage billing."}
        </Alert>
      )}
      {deletion?.requested && <Alert tone="warning" title="This business is scheduled for deletion" action={<LinkButton href="/settings#data" size="sm" variant="inverse">Review</LinkButton>}>Everything works until {deletion.scheduled_for ? new Date(deletion.scheduled_for).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "the scheduled date"}; you can cancel in Settings.</Alert>}
      {s && !path.startsWith("/settings/billing") && !path.startsWith("/settings/billing/payments") && (
        !s.active ? <Alert tone="error" title="Subscription inactive" action={<LinkButton href="/settings/billing" size="sm">Choose a plan</LinkButton>}>Your data is safe and your cards keep working, but editing, AI and sync are paused.</Alert>
        : s.status === "past_due" ? <Alert tone="warning" title="Payment failed" action={<LinkButton href="/settings/billing" size="sm" variant="inverse">Review billing</LinkButton>}>We couldn&rsquo;t charge your payment method. Access continues for now.</Alert>
        : null  // the trial is shown once, as the compact chip above the page (TrialChip), not as a banner on every page
      )}
    </div>
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
    if (s && !s.active) out.push({ id: "inactive", tone: "bad", title: "Subscription inactive", body: "Editing, AI and sync are paused. Your cards keep working.", href: "/settings/billing", cta: "Choose a plan" });
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
    <PopoverButton label="Business menu" align="left" buttonClass="flex min-h-11 max-w-[56vw] items-center gap-2 rounded-xl px-2 text-left hover:bg-surface-2 sm:max-w-[320px]"
      icon={<><span aria-hidden className="grid h-8 w-8 shrink-0 place-items-center rounded-[9px] bg-accent-tint text-[13px] font-semibold text-accent-ink">{tenant.name.slice(0, 1).toUpperCase()}</span>
        <span className="min-w-0"><span className="block truncate text-[15px] font-semibold leading-5">{tenant.name}</span></span><ChevronDown className="h-4 w-4 shrink-0 text-ink-400" aria-hidden /></>}>
      {(close) => (
        <div className="p-1">
          <p className="px-3 pb-1 pt-2 text-xs font-medium text-muted">{me.memberships.length > 1 ? "Your businesses" : "Your business"}</p>
          {me.memberships.map((m) => (
            <button key={m.tenant.id} type="button" onClick={() => { close(); if (m.tenant.id !== tenant.id) void switchTenant(m.tenant.id); }}
              className="flex min-h-11 w-full items-center justify-between gap-3 rounded-xl px-3 text-left font-medium hover:bg-surface-2">
              <span className="truncate">{m.tenant.name}</span>{m.tenant.id === tenant.id && <Check className="h-4 w-4 shrink-0 text-accent-ink" aria-label="Current" />}
            </button>
          ))}
          <div className="mt-1 border-t border-ink-100 pt-1"><Link href="/settings" onClick={close} className="flex min-h-11 items-center rounded-xl px-3 font-medium hover:bg-surface-2">Business settings</Link></div>
        </div>
      )}
    </PopoverButton>
  );

  const account = (
    <PopoverButton label="Account menu" buttonClass="grid h-11 w-11 place-items-center rounded-full hover:bg-surface-2" icon={avatar}>
      {(close) => (
        <div className="p-1">
          <div className="px-3 pb-2 pt-2"><p className="truncate font-semibold">{name}</p><p className="truncate text-[13px] text-muted">{me.user.email}</p></div>
          <div className="border-t border-ink-100 py-1">
            <Link href="/settings/account" onClick={close} className="flex min-h-11 items-center rounded-xl px-3 font-medium hover:bg-surface-2">Your account</Link>
            <Link href="/settings/appearance" onClick={close} className="flex min-h-11 items-center rounded-xl px-3 font-medium hover:bg-surface-2">Appearance</Link>
            {me.user.is_platform_admin && <Link href="/admin" onClick={close} className="flex min-h-11 items-center gap-2 rounded-xl px-3 font-medium hover:bg-surface-2"><ShieldCheck className="h-4 w-4" aria-hidden />Platform admin</Link>}
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
        <header className="sticky top-0 z-30 border-b border-ink-100 bg-canvas">
          <div className="mx-auto flex h-16 w-full max-w-[1240px] items-center justify-between gap-2 px-3 sm:px-6 lg:px-8">
            <div className="flex min-w-0 items-center gap-1.5">
              <Link href="/overview" aria-label="FlowQR home" className="hero-grad grid h-9 w-9 shrink-0 place-items-center rounded-[10px] !shadow-none md:hidden"><LogoMark size={19} variant="onAccent" /></Link>
              {business}
            </div>
            <div className="flex shrink-0 items-center gap-0.5 sm:gap-1">
              <LocationPicker className="hidden md:flex" />
              <button type="button" aria-label="Search (Ctrl K)" onClick={() => setPalette(true)} className={iconBtn}><Search className="h-[19px] w-[19px]" strokeWidth={1.75} aria-hidden /></button>
              <BellMenu notices={notices} />
              {account}
            </div>
          </div>
        </header>

        <main id="app-main" tabIndex={-1} className="mx-auto w-full min-w-0 max-w-[1240px] px-4 pb-[calc(88px+env(safe-area-inset-bottom))] pt-5 outline-none sm:px-6 md:pb-12 lg:px-8">
          <div className="mb-3 flex flex-wrap items-center gap-2 empty:hidden"><TrialChip s={s ?? null} /><LocationPicker className="md:hidden" /></div>
          <Banners s={s ?? null} deletion={deletion ?? null} />
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
