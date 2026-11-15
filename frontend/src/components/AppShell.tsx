"use client";
import { Check, ChevronDown, LogOut, Search, ShieldCheck } from "lucide-react";
import { MotionConfig } from "motion/react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api, errorMessage } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { LocationScopeProvider, useLocationScope } from "@/lib/location-scope";
import { locate, navFor } from "@/lib/nav";
import { useAppChrome } from "@/lib/theme";
import type { SubscriptionInfo } from "@/lib/types";
import { useFetch } from "@/lib/use-api";
import { CommandPalette } from "./shell/CommandPalette";
import { BellMenu } from "./shell/Bell";
import { HelpMenu, iconBtn, MobileBar, PopoverButton, Rail, SectionNav, SubNav, ThemeToggle, UtilButtons, type Notice } from "./shell/parts";
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

function LocationPicker() {
  const { locations, locationId, setLocationId } = useLocationScope();
  if (locations.length < 2) return null; // one location: nothing to choose
  return (
    <label className="flex items-center gap-2 text-[13px] text-muted">
      <span className="hidden sm:inline">Location</span>
      <select aria-label="Show data for location" value={locationId ?? ""} onChange={(e) => setLocationId(e.target.value || undefined)}
        className="min-h-10 max-w-[220px] rounded-full bg-surface px-4 text-sm font-medium text-ink shadow-pill">
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
    <div className="mb-5 space-y-3 empty:hidden">
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
 * The logged-in app frame (DESIGN.md §4): floating pills on a soft canvas. Top bar = brand, the four sections, search / notifications /
 * help, and the account menu. Left rail = the current section's pages, theme toggle, help and log out. On phones the sections move to a
 * floating bottom pill and the pages to a chip row. Every page keeps its own URL; this only decides how it is reached.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { me, tenant, role, loading, logout, refresh } = useAuth();
  const path = usePathname();
  const router = useRouter();
  const [palette, setPalette] = useState(false);
  useAppChrome();
  const sub = useFetch<SubscriptionInfo>(tenant ? "/billing/subscription" : null);
  const deletion = useFetch<{ requested: boolean; scheduled_for: string | null }>(role === "owner" ? "/account/deletion" : null).data;
  const legal = useFetch<{ support_email: string | null }>("/legal/info").data;
  const sections = useMemo(() => navFor(role), [role]);

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
  useEffect(() => setPalette(false), [path]);

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

  const here = locate(path);
  const section = here ? sections.find((x) => x.id === here.section.id) ?? null : null;
  const switchTenant = async (id: string) => { await api("/auth/select-tenant", { method: "POST", params: { tenant_id: id } }); await refresh(); router.refresh(); };
  const name = me.user.full_name?.trim() || me.user.email;
  const avatar = <span aria-hidden className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-gradient-to-br from-[#3b3540] to-[#131014] text-[13px] font-semibold text-pure-white">{initials(me.user.full_name, me.user.email)}</span>;
  const help = (inRail?: boolean) => <HelpMenu supportEmail={legal?.support_email} onSearch={() => setPalette(true)} align={inRail ? "left" : "right"} inRail={inRail} />;

  const account = (
    <PopoverButton label="Account menu" buttonClass="pill flex h-14 items-center gap-2.5 pl-2.5 pr-2.5 text-left lg:pr-4"
      icon={<>{avatar}<span className="hidden min-w-0 xl:block"><span className="block max-w-[160px] truncate text-sm font-semibold leading-4">{name}</span><span className="block max-w-[160px] truncate text-xs leading-4 text-muted">{tenant.name}</span></span><ChevronDown className="hidden h-4 w-4 text-muted xl:block" aria-hidden /></>}>
      {(close) => (
        <div className="p-1">
          <div className="px-3 pb-2 pt-2"><p className="truncate font-semibold">{name}</p><p className="truncate text-[13px] text-muted">{me.user.email}</p></div>
          {me.memberships.length > 1 && (
            <div className="border-t border-line py-1">
              <p className="px-3 pb-1 pt-2 text-xs font-medium text-muted">Switch business</p>
              {me.memberships.map((m) => (
                <button key={m.tenant.id} type="button" onClick={() => { close(); if (m.tenant.id !== tenant.id) void switchTenant(m.tenant.id); }}
                  className="flex w-full items-center justify-between gap-3 rounded-full px-3 py-2.5 text-left font-medium hover:bg-surface-2">
                  <span className="truncate">{m.tenant.name}</span>{m.tenant.id === tenant.id && <Check className="h-4 w-4 shrink-0 text-accent-ink" aria-label="Current" />}
                </button>
              ))}
            </div>
          )}
          <div className="border-t border-line py-1">
            <Link href="/settings/account" onClick={close} className="block rounded-full px-3 py-2.5 font-medium hover:bg-surface-2">Your account</Link>
            <Link href="/settings" onClick={close} className="block rounded-full px-3 py-2.5 font-medium hover:bg-surface-2">Business settings</Link>
            <Link href="/settings/appearance" onClick={close} className="block rounded-full px-3 py-2.5 font-medium hover:bg-surface-2">Appearance</Link>
            {me.user.is_platform_admin && <Link href="/admin" onClick={close} className="flex items-center gap-2 rounded-full px-3 py-2.5 font-medium hover:bg-surface-2"><ShieldCheck className="h-4 w-4" aria-hidden />Platform admin</Link>}
            <div className="flex items-center justify-between gap-2 px-3 py-1.5 lg:hidden"><span className="font-medium">Theme</span><ThemeToggle vertical={false} /></div>
            <button type="button" onClick={() => { close(); void logout(); }} className="flex w-full items-center gap-2 rounded-full px-3 py-2.5 text-left font-medium text-neg hover:bg-neg-tint"><LogOut className="h-4 w-4" aria-hidden />Log out</button>
          </div>
        </div>
      )}
    </PopoverButton>
  );

  return (
    <MotionConfig reducedMotion="user">
    <LocationScopeProvider>
    <div className="min-h-dvh bg-canvas-outer lg:p-5">
      <div className="mx-auto min-h-dvh w-full max-w-[1440px] bg-canvas px-4 pb-32 pt-4 sm:px-6 lg:min-h-[calc(100dvh-40px)] lg:rounded-frame lg:px-10 lg:pb-10 lg:pt-6">
        <header className="relative z-50 flex items-center justify-between gap-3 lg:gap-6">
          <Link href="/overview" aria-label="FlowQR overview" className="pill flex h-14 shrink-0 items-center gap-2.5 pl-2 pr-5 text-[15px] font-semibold">
            <span className="hero-grad grid h-10 w-10 place-items-center rounded-full !shadow-none"><LogoMark size={20} variant="onAccent" /></span>FlowQR
          </Link>
          <div className="hidden flex-1 justify-center lg:flex"><SectionNav path={path} /></div>
          <div className="flex items-center gap-3">
            <div className="pill flex h-14 items-center px-1.5">
              <button type="button" aria-label="Search (Ctrl K)" onClick={() => setPalette(true)} className={iconBtn}><Search className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden /></button>
              <BellMenu notices={notices} />
              <div className="hidden lg:block">{help()}</div>
            </div>
            {account}
          </div>
        </header>

        <div className="mt-6 lg:mt-2 lg:grid lg:grid-cols-[52px_minmax(0,1fr)] lg:gap-6">
          {section ? <Rail section={section} path={path} util={<UtilButtons onLogout={() => void logout()} help={help(true)} />} /> : <div className="hidden lg:block" />}
          <main id="app-main" className="min-w-0 lg:pt-2">
            <SubNav path={path} section={section} />
            <div className="mb-3 flex flex-wrap items-center justify-end gap-2 empty:hidden"><TrialChip s={s ?? null} /><LocationPicker /></div>
            <Banners s={s ?? null} deletion={deletion ?? null} />
            {children}
          </main>
        </div>
      </div>
      <MobileBar path={path} />
      <CommandPalette open={palette} onClose={() => setPalette(false)} sections={sections} />
    </div>
    </LocationScopeProvider>
    </MotionConfig>
  );
}
