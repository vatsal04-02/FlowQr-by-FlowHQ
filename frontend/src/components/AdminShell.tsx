"use client";
import clsx from "clsx";
import { Activity, BadgeIndianRupee, CreditCard, Gauge, LayoutDashboard, ListChecks, LogOut, QrCode, ScrollText, ShieldCheck, SlidersHorizontal, UserSearch, Users } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { useAppChrome } from "@/lib/theme";
import { Logo } from "./ui/Brand";
import { Alert, Spinner } from "./ui/Card";

const NAV = [
  { href: "/admin", label: "Overview", icon: LayoutDashboard }, { href: "/admin/customers", label: "Businesses", icon: Users }, { href: "/admin/users", label: "Users", icon: UserSearch },
  { href: "/admin/cards", label: "Cards", icon: QrCode }, { href: "/admin/billing", label: "Billing", icon: CreditCard },
  { href: "/admin/plans", label: "Plans", icon: SlidersHorizontal }, { href: "/admin/finance", label: "Finance", icon: Gauge }, { href: "/admin/whatsapp-prices", label: "WhatsApp prices", icon: BadgeIndianRupee },
  { href: "/admin/queue", label: "Work queue", icon: ListChecks }, { href: "/admin/ops", label: "Operations", icon: Activity },
  { href: "/admin/audit", label: "Audit", icon: ScrollText },
];

/**
 * Platform-admin console: the same brand, tokens and components as the customer app, in a denser layout (docs/DESIGN.md). A 220px sidebar from tablet width up; on a phone a
 * scrolling tab strip under the top bar. Only reachable by is_platform_admin (also enforced server-side on every /admin API).
 */
export function AdminShell({ children }: { children: ReactNode }) {
  const { me, loading, logout } = useAuth();
  const path = usePathname();
  const router = useRouter();
  useAppChrome();
  useEffect(() => { if (!loading && !me) router.replace("/login"); }, [loading, me, router]);
  if (loading || !me) return <div className="grid min-h-dvh place-items-center"><Spinner /></div>;
  if (!me.user.is_platform_admin) return <div className="mx-auto max-w-md p-8"><Alert tone="error" title="Platform admins only">You don&rsquo;t have access to this area.</Alert></div>;
  const active = (h: string) => (h === "/admin" ? path === h : path.startsWith(h));
  const brand = (
    <span className="flex items-center gap-2.5">
      <Logo href="/admin" auto tagline={false} size={26} label="Platform admin home" />
      <span className="text-[13px] font-medium text-muted">Admin</span>
    </span>
  );
  return (
    <div className="min-h-dvh bg-canvas">
      <aside aria-label="Admin navigation" className="fixed inset-y-0 left-0 z-40 hidden w-[220px] flex-col border-r border-ink-100 bg-surface md:flex">
        <div className="flex h-16 shrink-0 items-center px-4">{brand}</div>
        <nav aria-label="Admin" className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2.5 pb-3">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} aria-current={active(n.href) ? "page" : undefined}
              className={clsx("relative flex min-h-10 items-center gap-3 rounded-[10px] pl-3 pr-2 text-[14px] transition-colors", active(n.href) ? "bg-surface-2 font-semibold text-ink" : "font-medium text-ink-700 hover:bg-surface-2 hover:text-ink")}>
              {active(n.href) && <span aria-hidden className="absolute inset-y-2 left-0 w-[3px] rounded-r-full bg-accent" />}
              <n.icon className={clsx("h-[18px] w-[18px] shrink-0", active(n.href) ? "text-accent-ink" : "text-ink-500")} strokeWidth={1.75} aria-hidden />{n.label}
            </Link>
          ))}
        </nav>
        <div className="space-y-0.5 border-t border-ink-100 p-2.5">
          {me.memberships.length > 0 && <Link href="/overview" className="flex min-h-10 items-center rounded-[10px] px-3 text-[14px] font-medium text-ink-700 hover:bg-surface-2">My business</Link>}
          <button type="button" onClick={() => void logout()} className="flex min-h-10 w-full items-center gap-3 rounded-[10px] px-3 text-left text-[14px] font-medium text-ink-700 hover:bg-surface-2"><LogOut className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden />Log out</button>
        </div>
      </aside>

      <div className="md:pl-[220px]">
        <header className="sticky top-0 z-30 border-b border-ink-100 bg-canvas md:hidden">
          <div className="flex h-14 items-center justify-between gap-2 px-3">
            {brand}
            <div className="flex items-center gap-1">
              <span className="inline-flex items-center gap-1 rounded-full bg-surface-3 px-2.5 py-0.5 text-xs font-semibold"><ShieldCheck className="h-3.5 w-3.5" aria-hidden />FlowHQ staff</span>
              <button type="button" onClick={() => void logout()} aria-label="Log out" className="grid h-11 w-11 place-items-center rounded-full text-ink-600 hover:bg-surface-2"><LogOut className="h-[18px] w-[18px]" aria-hidden /></button>
            </div>
          </div>
          <nav aria-label="Admin mobile" className="no-scrollbar flex overflow-x-auto px-2">
            {NAV.map((n) => (
              <Link key={n.href} href={n.href} aria-current={active(n.href) ? "page" : undefined}
                className={clsx("relative inline-flex min-h-11 shrink-0 items-center whitespace-nowrap px-3 text-sm font-medium", active(n.href) ? "text-ink" : "text-muted")}>
                {n.label}{active(n.href) && <span aria-hidden className="absolute inset-x-3 bottom-0 h-0.5 rounded-full bg-accent" />}
              </Link>
            ))}
          </nav>
        </header>
        <main className="mx-auto w-full min-w-0 max-w-[1400px] px-4 py-5 sm:px-6 md:py-6">{children}</main>
      </div>
    </div>
  );
}
