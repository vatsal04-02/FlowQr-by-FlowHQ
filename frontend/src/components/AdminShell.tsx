"use client";
import clsx from "clsx";
import { Activity, CreditCard, Gauge, LayoutDashboard, ListChecks, LogOut, QrCode, ScrollText, ShieldCheck, SlidersHorizontal, UserSearch, Users } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { useAuth } from "@/lib/auth";
import { useAppChrome } from "@/lib/theme";
import { LogoMark } from "./ui/Brand";
import { Alert, Spinner } from "./ui/Card";

const NAV = [
  { href: "/admin", label: "Overview", icon: LayoutDashboard }, { href: "/admin/customers", label: "Customers", icon: Users }, { href: "/admin/users", label: "Users", icon: UserSearch },
  { href: "/admin/cards", label: "Cards", icon: QrCode }, { href: "/admin/billing", label: "Billing", icon: CreditCard },
  { href: "/admin/plans", label: "Plans", icon: SlidersHorizontal }, { href: "/admin/finance", label: "Finance", icon: Gauge },
  { href: "/admin/queue", label: "Work queue", icon: ListChecks }, { href: "/admin/ops", label: "Operations", icon: Activity },
  { href: "/admin/audit", label: "Audit", icon: ScrollText },
];

/** Platform-admin console: separate chrome, only reachable by is_platform_admin (also enforced server-side on every /admin API). */
export function AdminShell({ children }: { children: ReactNode }) {
  const { me, loading, logout } = useAuth();
  const path = usePathname();
  const router = useRouter();
  useAppChrome(); // same tokens and light/dark choice as the customer app (DESIGN.md §11); its own navigation stays
  useEffect(() => { if (!loading && !me) router.replace("/login"); }, [loading, me, router]);
  if (loading || !me) return <div className="grid min-h-dvh place-items-center"><Spinner /></div>;
  if (!me.user.is_platform_admin) return <div className="mx-auto max-w-md p-8"><Alert tone="error" title="Platform admins only">You don&rsquo;t have access to this area.</Alert></div>;
  const active = (h: string) => (h === "/admin" ? path === h : path.startsWith(h));
  return (
    <div className="min-h-dvh bg-canvas">
      <header className="sticky top-0 z-30 bg-ink text-white">
        <div className="mx-auto flex max-w-7xl items-center gap-4 px-4 py-2.5 sm:px-6">
          <Link href="/admin" className="flex items-center gap-2.5 rounded-lg" aria-label="Platform admin home"><LogoMark size={28} /><span className="font-display font-semibold">FlowQR <span className="text-ink-200">Admin</span></span></Link>
          <span className="hidden items-center gap-1 rounded-full bg-white/10 px-2.5 py-0.5 text-xs font-semibold sm:inline-flex"><ShieldCheck className="h-3.5 w-3.5" aria-hidden />FlowHQ staff</span>
          <nav aria-label="Admin" className="ml-2 hidden flex-1 gap-1 lg:flex">
            {NAV.map((n) => <Link key={n.href} href={n.href} aria-current={active(n.href) ? "page" : undefined} className={clsx("inline-flex min-h-10 items-center gap-2 rounded-lg px-3 text-sm font-semibold", active(n.href) ? "bg-white/15" : "text-ink-200 hover:bg-white/10")}><n.icon className="h-4 w-4" aria-hidden />{n.label}</Link>)}
          </nav>
          <div className="ml-auto flex items-center gap-1">
            {me.memberships.length > 0 && <Link href="/overview" className="tap hidden items-center rounded-lg px-3 text-sm text-ink-200 hover:bg-white/10 sm:inline-flex">My business</Link>}
            <button onClick={() => void logout()} aria-label="Log out" className="tap grid place-items-center rounded-lg text-ink-200 hover:bg-white/10"><LogOut className="h-4 w-4" aria-hidden /></button>
          </div>
        </div>
        <nav aria-label="Admin mobile" className="flex gap-1 overflow-x-auto border-t border-white/10 px-3 py-1.5 lg:hidden">
          {NAV.map((n) => <Link key={n.href} href={n.href} aria-current={active(n.href) ? "page" : undefined} className={clsx("inline-flex min-h-10 shrink-0 items-center gap-1.5 rounded-lg px-3 text-sm font-semibold", active(n.href) ? "bg-white/15" : "text-ink-200")}><n.icon className="h-4 w-4" aria-hidden />{n.label}</Link>)}
        </nav>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6">{children}</main>
    </div>
  );
}
