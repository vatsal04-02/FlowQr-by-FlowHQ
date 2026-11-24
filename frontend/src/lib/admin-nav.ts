import { Activity, BadgeIndianRupee, Building2, CalendarDays, CreditCard, Gauge, LayoutDashboard, ListChecks, QrCode, ScrollText, ShieldCheck, SlidersHorizontal, UserSearch } from "lucide-react";
import type { ComponentType } from "react";

export type AdminItem = { href: string; label: string; icon: ComponentType<{ className?: string; strokeWidth?: number; "aria-hidden"?: boolean }>; hint?: string };
export type AdminGroup = { id: string; label: string; items: AdminItem[] };

/**
 * The operator console's navigation, in one place for the sidebar, the phone drawer and the bottom bar. Every entry is an existing page (nothing here adds a route); the groups are the
 * operator's own questions: how is the business doing, who are the clients, what are they paying, what do plans cost, is it healthy, who did what.
 */
export const ADMIN_GROUPS: AdminGroup[] = [
  { id: "command", label: "Command center", items: [
    { href: "/admin", label: "Overview", icon: LayoutDashboard, hint: "Clients, revenue, what needs you" },
    { href: "/admin/queue", label: "Work queue", icon: ListChecks, hint: "Things waiting for a person" },
  ] },
  { id: "clients", label: "Clients", items: [
    { href: "/admin/customers", label: "Businesses", icon: Building2, hint: "All clients, trials, suspended" },
    { href: "/admin/users", label: "Users", icon: UserSearch, hint: "Logins and sessions" },
    { href: "/admin/agency", label: "Agency onboarding", icon: ShieldCheck, hint: "Google access on behalf of clients" },
    { href: "/admin/managed-usage", label: "Managed usage", icon: Gauge, hint: "Usage of businesses we run" },
  ] },
  { id: "money", label: "Subscriptions & revenue", items: [
    { href: "/admin/billing", label: "Subscriptions & payments", icon: CreditCard, hint: "Renewals, payments, card orders" },
    { href: "/admin/finance", label: "Revenue & costs", icon: Gauge, hint: "MRR, ARR, margin, costs" },
  ] },
  { id: "plans", label: "Plans & pricing", items: [
    { href: "/admin/plans", label: "Plans & limits", icon: SlidersHorizontal },
    { href: "/admin/whatsapp-prices", label: "WhatsApp prices", icon: BadgeIndianRupee },
    { href: "/admin/whatsapp-ai", label: "WhatsApp assistant", icon: BadgeIndianRupee },
    { href: "/admin/whatsapp-entry-window", label: "WhatsApp free window", icon: CalendarDays },
    { href: "/admin/whatsapp-festivals", label: "WhatsApp festivals", icon: CalendarDays },
  ] },
  { id: "ops", label: "Operations", items: [
    { href: "/admin/ops", label: "System health", icon: Activity, hint: "Checks, workers, integrations" },
    { href: "/admin/cards", label: "Cards & inventory", icon: QrCode, hint: "Batches, assignment, fulfilment" },
  ] },
  { id: "admin", label: "Administration", items: [
    { href: "/admin/audit", label: "Audit log", icon: ScrollText, hint: "Who did what" },
  ] },
];

export const ADMIN_ITEMS: AdminItem[] = ADMIN_GROUPS.flatMap((g) => g.items);
/** The four pages used most from a phone; the fifth bottom-bar button opens the full menu. */
export const ADMIN_BOTTOM = ["/admin", "/admin/customers", "/admin/billing", "/admin/ops"] as const;

export const adminActive = (path: string, href: string) => (href === "/admin" ? path === href : path === href || path.startsWith(href + "/"));
/** The page a path belongs to: the longest matching href wins (so /admin/customers/123 is Businesses). */
export function adminHere(path: string): { group: AdminGroup; item: AdminItem } | null {
  let best: { group: AdminGroup; item: AdminItem } | null = null;
  for (const g of ADMIN_GROUPS) for (const item of g.items) if (adminActive(path, item.href) && (!best || item.href.length > best.item.href.length)) best = { group: g, item };
  return best;
}
