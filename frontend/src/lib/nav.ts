import {
  Activity, BarChart3, Building2, CircleHelp, CreditCard, Home, ListChecks, Megaphone, MapPin, MessageSquare, QrCode, Settings2, Sparkles, type LucideIcon,
} from "lucide-react";
import type { Role } from "./types";

/**
 * One navigation system for the whole app (docs/DESIGN.md, "Navigation"). Phones: a bottom bar with Home, Reviews, Visibility, Results and More.
 * Desktop and tablet: one left sidebar. Both read this file, so a page is added or renamed in exactly one place.
 *
 * Words are for shop, salon, clinic and restaurant owners, not for SEO people: technical names live in tooltips and detail views.
 * Every old URL keeps working through legacy-routes.mjs; pages for unfinished integrations (WhatsApp inbox, Studio calendar, brand kit, assets, social) are
 * deliberately not listed (their routes and source are untouched).
 */
export type Tab = { href: string; label: string; only?: Role[] };
export type Child = {
  href: string; label: string;
  /** other paths that belong to this page (detail pages) so the right tab stays highlighted */
  also?: string[];
  /** a second row of tabs shown only while this page is open (for pages that share a theme, for example Business info, Hours, Posts, Photos) */
  tabs?: Tab[];
  only?: Role[];
};
export type Group = "main" | "tools" | "assistant" | "account";
export type Dest = {
  id: string; href: string; label: string;
  /** one short line in search and tooltips */
  desc: string; icon: LucideIcon; group: Group;
  children?: Child[]; also?: string[]; only?: Role[];
};

export const GROUP_LABEL: Record<Group, string | null> = { main: null, tools: "Business tools", assistant: "Assistant", account: "Account" };

export const DESTS: Dest[] = [
  { id: "home", href: "/overview", label: "Home", desc: "Your business at a glance", icon: Home, group: "main" },
  { id: "reviews", href: "/gbp/reviews", label: "Reviews", desc: "Read, reply and approve", icon: MessageSquare, group: "main", children: [
    { href: "/gbp/reviews", label: "All reviews" },
    { href: "/reputation/drafts", label: "Draft replies" },
    { href: "/reputation/insights", label: "What customers are saying" },
  ] },
  { id: "visibility", href: "/seo", label: "Visibility", desc: "How easily customers find you on Google", icon: MapPin, group: "main", children: [
    { href: "/seo", label: "Google Maps" },
    { href: "/seo/searches", label: "Searches people use" },
    { href: "/seo/competitors", label: "Nearby competitors" },
    { href: "/seo/profile", label: "Your Google profile", tabs: [
      { href: "/seo/profile", label: "Improve" }, { href: "/gbp/info", label: "Business info" }, { href: "/gbp/hours", label: "Opening hours" }, { href: "/gbp/posts", label: "Posts" }, { href: "/gbp/photos", label: "Photos" },
    ] },
    { href: "/seo/rank", label: "Track search terms" },
  ] },
  { id: "results", href: "/analytics/performance", label: "Results", desc: "What Google, reviews and cards brought you", icon: BarChart3, group: "main", children: [
    { href: "/analytics/performance", label: "Google activity" },
    { href: "/analytics/reviews", label: "Reviews" },
    { href: "/analytics/funnel", label: "QR & NFC" },
    { href: "/analytics/campaigns", label: "Campaigns" },
    { href: "/analytics/reports", label: "Reports" },
  ] },
  { id: "cards", href: "/gbp/cards", label: "QR & NFC Cards", desc: "Cards that ask customers for a review", icon: QrCode, group: "tools", children: [
    { href: "/gbp/cards", label: "Your cards" },
    { href: "/gbp/cards/designs", label: "Designs & export" },
    { href: "/reputation/assistant", label: "What customers see", also: ["/reputation/assistant/settings"] },
  ] },
  { id: "campaigns", href: "/gbp/campaigns", label: "Campaigns", desc: "Review pages your cards open", icon: Megaphone, group: "tools", children: [
    { href: "/gbp/campaigns", label: "Review campaigns" },
    { href: "/gbp/campaigns/landing", label: "Page design" },
    { href: "/gbp/campaigns/guide", label: "Setup guide" },
  ] },
  { id: "locations", href: "/gbp/locations", label: "Locations", desc: "Your branches and Google connection", icon: Building2, group: "tools", children: [
    { href: "/gbp/locations", label: "Locations & Google" },
    { href: "/overview/locations", label: "Compare branches" },
  ] },
  { id: "assistant", href: "/ai/today", label: "AI Assistant", desc: "Today's plan and helpers", icon: Sparkles, group: "assistant", children: [
    { href: "/ai/today", label: "Today" },
    { href: "/ai/automations", label: "Helpers" },
    { href: "/ai/studio", label: "Write a post" },
  ] },
  { id: "tasks", href: "/ai/tasks", label: "Tasks & Approvals", desc: "What to do, and what waits for you", icon: ListChecks, group: "assistant", children: [
    { href: "/ai/tasks", label: "Tasks" },
    { href: "/ai/approvals", label: "Waiting for your approval" },
    { href: "/ai/activity", label: "Activity" },
  ] },
  { id: "settings", href: "/settings", label: "Settings", desc: "Business, team, billing and more", icon: Settings2, group: "account", children: [
    { href: "/settings", label: "Business" },
    { href: "/settings/account", label: "Account" },
    { href: "/settings/team", label: "Team" },
    { href: "/settings/billing", label: "Billing", only: ["owner", "admin"], tabs: [{ href: "/settings/billing", label: "Plan" }, { href: "/settings/billing/payments", label: "Payments & orders" }] },
    { href: "/settings/connections", label: "Connections" },
    { href: "/settings/notifications", label: "Notifications" },
    { href: "/settings/ai/voice", label: "AI & automation", also: ["/settings/ai"], tabs: [
      { href: "/settings/ai/voice", label: "Brand voice" }, { href: "/settings/ai/brain", label: "Business brain" }, { href: "/settings/ai/autonomy", label: "Autonomy", only: ["owner", "admin"] }, { href: "/settings/ai/usage", label: "Usage", only: ["owner", "admin"] },
    ] },
    { href: "/settings/appearance", label: "Appearance" },
    { href: "/settings/audit", label: "Audit", only: ["owner", "admin"] },
  ] },
];

/** The four destinations on the phone's bottom bar, in order. The fifth, More, opens the sheet below. */
export const BOTTOM_IDS = ["home", "reviews", "visibility", "results"] as const;

export type MoreItem = { href: string; label: string; desc: string; icon: LucideIcon; only?: Role[]; help?: boolean };
export const MORE_GROUPS: { label: string; items: MoreItem[] }[] = [
  { label: "Business tools", items: [
    { href: "/gbp/cards", label: "QR & NFC Cards", desc: "Cards that ask for reviews", icon: QrCode },
    { href: "/gbp/campaigns", label: "Campaigns", desc: "Review pages your cards open", icon: Megaphone },
    { href: "/gbp/locations", label: "Locations", desc: "Your branches and Google", icon: Building2 },
  ] },
  { label: "Business assistant", items: [
    { href: "/ai/today", label: "AI Assistant", desc: "Today's plan and helpers", icon: Sparkles },
    { href: "/ai/tasks", label: "Tasks & Approvals", desc: "What waits for you", icon: ListChecks },
    { href: "/ai/activity", label: "Activity", desc: "What the assistant did", icon: Activity },
  ] },
  { label: "Account", items: [
    { href: "/settings", label: "Settings", desc: "Business, team, alerts", icon: Settings2 },
    { href: "/settings/billing", label: "Billing", desc: "Plan and payments", icon: CreditCard, only: ["owner", "admin"] },
    { href: "/help", label: "Help & Support", desc: "Search, or email us", icon: CircleHelp, help: true },
  ] },
];

/** The navigation as this person sees it: pages for other roles are left out ("hide, don't just disable"). The API enforces access either way. */
export function navFor(role: Role | null): Dest[] {
  const ok = (only?: Role[]) => !only || (role !== null && only.includes(role));
  return DESTS.filter((d) => ok(d.only)).map((d) => (d.children ? { ...d, children: d.children.filter((c) => ok(c.only)).map((c) => (c.tabs ? { ...c, tabs: c.tabs.filter((t) => ok(t.only)) } : c)) } : d));
}
export const moreFor = (role: Role | null) => MORE_GROUPS.map((g) => ({ ...g, items: g.items.filter((i) => !i.only || (role !== null && i.only.includes(role))) }));

export type Located = { dest: Dest; child: Child | null; tab: Tab | null; detail: boolean };

const covers = (path: string, h: string) => path === h || path.startsWith(h + "/");
const hrefs = (d: Dest): { h: string; child: Child | null; tab: Tab | null }[] => [
  { h: d.href, child: null, tab: null },
  ...(d.also ?? []).map((h) => ({ h, child: null, tab: null })),
  ...(d.children ?? []).flatMap((c) => [
    { h: c.href, child: c, tab: null },
    ...(c.also ?? []).map((h) => ({ h, child: c, tab: null })),
    ...(c.tabs ?? []).map((t) => ({ h: t.href, child: c, tab: t })),
  ]),
];

/** Which destination, page and tab a path belongs to: the longest matching prefix wins, so /seo/competitors never lights up "Google Maps" (/seo). */
export function locate(path: string): Located | null {
  let best: { dest: Dest; child: Child | null; tab: Tab | null; len: number; exact: boolean } | null = null;
  for (const d of DESTS) for (const x of hrefs(d)) {
    if (covers(path, x.h) && (!best || x.h.length > best.len)) best = { dest: d, child: x.child, tab: x.tab, len: x.h.length, exact: path === x.h };
  }
  if (!best) return null;
  return { dest: best.dest, child: best.child ?? best.dest.children?.find((c) => c.href === best!.dest.href) ?? null, tab: best.tab, detail: !best.exact };
}

/** Which of the five bottom-bar items is lit: one of the four, or More for every other page. */
export function bottomActive(path: string): string {
  const l = locate(path);
  if (!l) return "more";
  return (BOTTOM_IDS as readonly string[]).includes(l.dest.id) ? l.dest.id : "more";
}

/** Every path the app shell serves, for the no-flash theme script in the root layout (it must not touch marketing pages). */
export const APP_PREFIXES = Array.from(new Set(["/admin", ...DESTS.flatMap((d) => hrefs(d).map((x) => x.h))]));

