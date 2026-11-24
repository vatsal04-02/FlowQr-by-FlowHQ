import { Activity, BadgeIndianRupee, Building2, CalendarDays, CreditCard, Gauge, LayoutDashboard, ListChecks, QrCode, ScrollText, ShieldCheck, SlidersHorizontal, UserSearch } from "lucide-react";
import type { ComponentType } from "react";

export type AdminItem = { href: string; label: string; icon: ComponentType<{ className?: string; strokeWidth?: number; "aria-hidden"?: boolean }>; hint?: string; also?: string[]; badge?: "queue" | "ops"; short?: string };
export type AdminGroup = { id: string; label: string; items: AdminItem[] };

/**
 * The operator console's navigation, in one place for the sidebar, the phone More sheet and the bottom bar. Every entry is an existing page (nothing here adds a data route); the groups are
 * the operator's own questions: how is the business doing, who are the clients, where is the money and the stock, is the WhatsApp product set up, is the platform healthy.
 */
export const ADMIN_GROUPS: AdminGroup[] = [
  { id: "command", label: "Overview", items: [
    { href: "/admin", label: "Overview", icon: LayoutDashboard, hint: "Clients, revenue, what needs you" },
    { href: "/admin/queue", label: "Work queue", icon: ListChecks, hint: "Things waiting for a person", badge: "queue" },
  ] },
  { id: "clients", label: "Customers", items: [
    { href: "/admin/customers", label: "Businesses", short: "Customers", icon: Building2, hint: "All clients, trials, suspended" },
    { href: "/admin/users", label: "Users", icon: UserSearch, hint: "Logins and sessions" },
    { href: "/admin/agency", label: "Agency onboarding", icon: ShieldCheck, hint: "Google access on behalf of clients" },
    { href: "/admin/managed-usage", label: "Managed usage", icon: Gauge, hint: "Usage of businesses we run" },
  ] },
  { id: "money", label: "Cards and money", items: [
    { href: "/admin/cards", label: "Cards & inventory", short: "Cards", icon: QrCode, hint: "Batches, assignment, fulfilment" },
    { href: "/admin/billing", label: "Subscriptions & payments", icon: CreditCard, hint: "Renewals, payments, card orders" },
    { href: "/admin/finance", label: "Revenue & costs", icon: Gauge, hint: "MRR, ARR, margin, costs" },
    { href: "/admin/plans", label: "Plans & limits", icon: SlidersHorizontal },
  ] },
  { id: "whatsapp", label: "WhatsApp", items: [
    { href: "/admin/whatsapp", label: "WhatsApp settings", icon: BadgeIndianRupee, hint: "Prices, assistant, free window, festivals",
      also: ["/admin/whatsapp-prices", "/admin/whatsapp-ai", "/admin/whatsapp-entry-window", "/admin/whatsapp-festivals"] },
  ] },
  { id: "ops", label: "Platform", items: [
    { href: "/admin/ops", label: "System health", short: "Health", icon: Activity, hint: "Checks, workers, integrations", badge: "ops" },
    { href: "/admin/audit", label: "Audit log", icon: ScrollText, hint: "Who did what" },
  ] },
];

export const ADMIN_ITEMS: AdminItem[] = ADMIN_GROUPS.flatMap((g) => g.items);
/** The four pages used most from a phone (Overview, Customers, Cards, Health); the fifth bottom-bar button opens the full menu. */
export const ADMIN_BOTTOM = ["/admin", "/admin/customers", "/admin/cards", "/admin/ops"] as const;

export const adminActive = (path: string, href: string) => (href === "/admin" ? path === href : path === href || path.startsWith(href + "/"));
/** The page a path belongs to: the longest matching href wins (so /admin/customers/123 is Businesses). */
export function adminHere(path: string): { group: AdminGroup; item: AdminItem } | null {
  let best: { group: AdminGroup; item: AdminItem; len: number } | null = null;
  for (const g of ADMIN_GROUPS) for (const item of g.items) for (const h of [item.href, ...(item.also ?? [])]) if (adminActive(path, h) && (!best || h.length > best.len)) best = { group: g, item, len: h.length };
  return best ? { group: best.group, item: best.item } : null;
}
