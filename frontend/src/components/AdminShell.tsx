"use client";
import clsx from "clsx";
import { ChevronDown, LogOut, Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { ADMIN_BOTTOM, ADMIN_GROUPS, ADMIN_ITEMS, adminActive, adminHere } from "@/lib/admin-nav";
import { useAuth } from "@/lib/auth";
import { useAdminCounts, type AdminCount } from "@/lib/use-admin-counts";
import { useAppChrome } from "@/lib/theme";
import { Logo } from "./ui/Brand";
import { Alert, Spinner } from "./ui/Card";

const KEY = "flowqr:admin-nav";

/** A count that always says what it is: the number, with a screen-reader sentence, in red for critical and amber for attention. */
function Count({ c, label, className }: { c: AdminCount; label: string; className?: string }) {
  if (!c) return null;
  return <span className={clsx("inline-flex min-w-[20px] items-center justify-center rounded-full px-1.5 text-[11px] font-bold leading-5 text-white", c.tone === "bad" ? "bg-[#B42318]" : "bg-[#B45309]", className)}><span aria-hidden>{c.n}</span><span className="sr-only">{c.n} {label}</span></span>;
}

/** The grouped list, used by the desktop sidebar and the phone drawer. A group holding the current page is always open; the rest remember how the operator left them. */
function NavList({ path, onGo, counts }: { path: string; onGo?: () => void; counts: { ops: AdminCount; queue: AdminCount } }) {
  const here = adminHere(path);
  const [shut, setShut] = useState<Record<string, boolean>>({ plans: true });  // the WhatsApp rate pages start folded until the operator opens them
  useEffect(() => { try { const v = localStorage.getItem(KEY); if (v) setShut(JSON.parse(v)); } catch { /* private mode */ } }, []);
  const toggle = (id: string) => setShut((s) => { const n = { ...s, [id]: !s[id] }; try { localStorage.setItem(KEY, JSON.stringify(n)); } catch { /* ignore */ } return n; });
  return (
    <nav aria-label="Admin" className="space-y-3">
      {ADMIN_GROUPS.map((g) => {
        const open = here?.group.id === g.id || !shut[g.id];
        return (
          <div key={g.id}>
            <button type="button" onClick={() => toggle(g.id)} aria-expanded={open} aria-controls={`ag-${g.id}`} disabled={here?.group.id === g.id}
              className="flex min-h-9 w-full items-center justify-between rounded-lg px-3 text-left text-[12px] font-semibold uppercase tracking-[.04em] text-muted hover:text-ink disabled:cursor-default disabled:hover:text-muted">
              {g.label}{here?.group.id !== g.id && <ChevronDown aria-hidden className={clsx("h-3.5 w-3.5 transition-transform", open && "rotate-180")} />}
            </button>
            {open && (
              <ul id={`ag-${g.id}`} className="mt-0.5 space-y-0.5">
                {g.items.map((n) => {
                  const on = here?.item.href === n.href;
                  return (
                    <li key={n.href}>
                      <Link href={n.href} onClick={onGo} aria-current={on ? "page" : undefined}
                        className={clsx("relative flex min-h-11 items-center gap-3 rounded-[10px] pl-3 pr-2 text-[14px] transition-colors md:min-h-10", on ? "bg-surface-2 font-semibold text-ink" : "font-medium text-ink-700 hover:bg-surface-2 hover:text-ink")}>
                        {on && <span aria-hidden className="absolute inset-y-2 left-0 w-[3px] rounded-r-full bg-accent" />}
                        <n.icon className={clsx("h-[18px] w-[18px] shrink-0", on ? "text-accent-ink" : "text-ink-500")} strokeWidth={1.75} aria-hidden /><span className="min-w-0 flex-1 truncate">{n.label}</span>{n.badge && <Count c={counts[n.badge]} label={n.badge === "ops" ? "checks need attention" : "items waiting"} className="mr-1" />}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        );
      })}
    </nav>
  );
}

/**
 * Platform-admin console. A 232px grouped sidebar from tablet width up; on a phone a compact top bar with a menu button (slide-out drawer with every page, grouped) and a bottom bar with
 * the four pages an operator opens most, plus Menu. Only reachable by is_platform_admin (also enforced server-side on every /admin API).
 */
export function AdminShell({ children }: { children: ReactNode }) {
  const { me, loading, logout } = useAuth();
  const path = usePathname();
  const router = useRouter();
  const [drawer, setDrawer] = useState(false);
  useAppChrome();
  const counts = useAdminCounts(!!me?.user.is_platform_admin);
  useEffect(() => { if (!loading && !me) router.replace("/login"); }, [loading, me, router]);
  useEffect(() => { setDrawer(false); }, [path]);
  useEffect(() => {
    if (!drawer) return;
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setDrawer(false); };
    document.addEventListener("keydown", esc);
    const prev = document.body.style.overflow; document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", esc); document.body.style.overflow = prev; };
  }, [drawer]);
  if (loading || !me) return <div className="grid min-h-dvh place-items-center"><Spinner /></div>;
  if (!me.user.is_platform_admin) return <div className="mx-auto max-w-md p-8"><Alert tone="error" title="Platform admins only">You don&rsquo;t have access to this area.</Alert></div>;
  const here = adminHere(path);
  const brand = (
    <span className="flex items-center gap-2.5">
      <Logo href="/admin" auto tagline={false} size={26} label="Platform admin home" />
      <span className="rounded-full bg-navy px-2 py-0.5 text-[11px] font-bold tracking-wide text-white">Admin</span>
    </span>
  );
  const foot = (
    <>
      {me.memberships.length > 0 && <Link href="/overview" className="flex min-h-11 items-center rounded-[10px] px-3 text-[14px] font-medium text-ink-700 hover:bg-surface-2 md:min-h-10">My business</Link>}
      <button type="button" onClick={() => void logout()} className="flex min-h-11 w-full items-center gap-3 rounded-[10px] px-3 text-left text-[14px] font-medium text-ink-700 hover:bg-surface-2 md:min-h-10"><LogOut className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden />Log out</button>
    </>
  );
  const bottom = ADMIN_BOTTOM.map((h) => ADMIN_ITEMS.find((i) => i.href === h)!);
  return (
    <div className="min-h-dvh bg-canvas">
      <aside aria-label="Admin navigation" className="fixed inset-y-0 left-0 z-40 hidden w-[232px] flex-col border-r border-ink-100 bg-surface md:flex">
        <div className="flex h-16 shrink-0 items-center px-4">{brand}</div>
        <div className="min-h-0 flex-1 overflow-y-auto px-2.5 pb-3"><NavList path={path} counts={counts} /></div>
        <div className="space-y-0.5 border-t border-ink-100 p-2.5">{foot}</div>
      </aside>

      <div className="md:pl-[232px]">
        <header className="sticky top-0 z-30 border-b border-ink-100 bg-canvas md:hidden">
          <div className="flex h-14 items-center justify-between gap-2 px-3">
            <button type="button" onClick={() => setDrawer(true)} aria-label="Open menu" aria-haspopup="dialog" className="grid h-11 w-11 shrink-0 place-items-center rounded-full text-ink hover:bg-surface-2"><Menu className="h-5 w-5" aria-hidden /></button>
            <p className="min-w-0 flex-1 truncate text-[15px] font-semibold">{here?.item.label ?? "Operator"}</p>
            <Logo href="/admin" auto markOnly tagline={false} size={28} label="Platform admin home" />
          </div>
        </header>
        <main className="mx-auto w-full min-w-0 max-w-[1400px] px-4 py-5 pb-24 sm:px-6 md:py-6 md:pb-6">{children}</main>
      </div>

      <nav aria-label="Admin quick links" className="fixed inset-x-0 bottom-0 z-30 border-t border-ink-100 bg-surface pb-[env(safe-area-inset-bottom)] md:hidden">
        <ul className="grid h-14 grid-cols-5">
          {bottom.map((n) => {
            const on = adminActive(path, n.href);
            return (
              <li key={n.href}><Link href={n.href} aria-current={on ? "page" : undefined} className={clsx("flex h-full flex-col items-center justify-center gap-0.5 text-[11px] font-medium", on ? "text-ink" : "text-muted")}>
                <span className="relative"><n.icon className="h-5 w-5" strokeWidth={on ? 2 : 1.75} aria-hidden />{n.badge && <Count c={counts[n.badge]} label="need attention" className="absolute -right-3 -top-1.5 !min-w-[16px] !px-1 !text-[10px] !leading-4" />}</span>{n.short ?? n.label}</Link></li>);
          })}
          <li><button type="button" onClick={() => setDrawer(true)} className="flex h-full w-full flex-col items-center justify-center gap-0.5 text-[11px] font-medium text-muted"><Menu className="h-5 w-5" strokeWidth={1.75} aria-hidden />Menu</button></li>
        </ul>
      </nav>

      {drawer && (
        <div className="fixed inset-0 z-50 md:hidden" role="dialog" aria-modal="true" aria-label="Admin menu">
          <button type="button" aria-label="Close menu" onClick={() => setDrawer(false)} className="adm-scrim absolute inset-0 bg-black/40" />
          <div className="adm-drawer absolute inset-y-0 left-0 flex w-[min(320px,86vw)] flex-col bg-surface shadow-xl">
            <div className="flex h-14 shrink-0 items-center justify-between px-4">{brand}<button type="button" onClick={() => setDrawer(false)} aria-label="Close menu" className="grid h-11 w-11 place-items-center rounded-full hover:bg-surface-2"><X className="h-5 w-5" aria-hidden /></button></div>
            <div className="min-h-0 flex-1 overflow-y-auto px-2.5 pb-3"><NavList path={path} onGo={() => setDrawer(false)} counts={counts} /></div>
            <div className="space-y-0.5 border-t border-ink-100 p-2.5 pb-[calc(0.625rem+env(safe-area-inset-bottom))]">{foot}</div>
          </div>
        </div>
      )}
    </div>
  );
}
