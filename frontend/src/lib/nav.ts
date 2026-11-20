import { CircleHelp } from "lucide-react";
import type { ComponentType } from "react";
import { GbpIcon } from "@/components/icons/Gbp";
import { ActivityGlyph, BillingGlyph, GrowthGlyph, HomeGlyph, LocationsGlyph, ReviewsGlyph, SettingsGlyph, TasksGlyph, TodayGlyph, WhatsAppGlyph } from "@/components/icons/Nav";
import type { Role } from "./types";

/** One of FlowQR's own glyphs (components/icons/Nav.tsx), a brand mark (GBP), or a lucide icon: all take the same props. */
export type NavIcon = ComponentType<{ className?: string; strokeWidth?: number; "aria-hidden"?: boolean | "true" | "false" }>;

/**
 * One navigation system for the whole app (docs/DESIGN.md). Phones: a bottom bar with Home, Reviews, GBP (Google Business Profile), Growth and More. Tablet and desktop: one left sidebar.
 * Both read this file, so a page is added or renamed in exactly one place. Each owner question has one home: am I getting better (Home), what do people say (Reviews),
 * do people find me on Google (GBP), how do I get more reviews (Growth). Every old URL keeps working through legacy-routes.mjs. Pages for unfinished integrations
 * (WhatsApp inbox, Studio calendar, brand kit, assets, social) are deliberately not listed (their routes and source are untouched).
 */
export type Tab = { href: string; label: string; also?: string[]; only?: Role[] };
export type Child = {
  href: string; label: string;
  /** other paths that belong to this page (detail pages, old pages) so the right tab stays highlighted */
  also?: string[];
  /** a second row for pages that share a theme; at most four, or it becomes a picker */
  tabs?: Tab[];
  only?: Role[];
};
export type Group = "main" | "tools" | "assistant" | "account";
export type Dest = { id: string; href: string; label: string; short?: string; desc: string; icon: NavIcon; group: Group; children?: Child[]; also?: string[]; only?: Role[]; flag?: "whatsapp" };
/** Server switches that show or hide a destination (me.integrations). A switched-off feature has no menu entry at all. */
export type NavFlags = { whatsapp?: boolean };

export const GROUP_LABEL: Record<Group, string | null> = { main: null, tools: "Business", assistant: "Assistant", account: "Account" };

export const DESTS: Dest[] = [
  { id: "home", href: "/overview", label: "Home", desc: "Growth score and this week's moves", icon: HomeGlyph, group: "main" },
  { id: "reviews", href: "/gbp/reviews", label: "Reviews", desc: "Read, reply, approve", icon: ReviewsGlyph, group: "main", children: [
    { href: "/gbp/reviews", label: "Inbox" },
    { href: "/reputation/drafts", label: "Drafts" },
    { href: "/reputation/insights", label: "Insights" },
  ] },
  { id: "seo", href: "/seo", label: "GBP", desc: "Google Business Profile: how you show up on Google", icon: GbpIcon, group: "main", children: [
    { href: "/seo", label: "Overview" },
    { href: "/seo/rankings", label: "Rankings", also: ["/seo/searches", "/seo/competitors"] },
    { href: "/seo/performance", label: "Performance" },
    { href: "/seo/profile", label: "Profile", tabs: [
      { href: "/seo/profile", label: "Checklist" }, { href: "/gbp/info", label: "Info", also: ["/gbp/hours"] }, { href: "/gbp/posts", label: "Posts" }, { href: "/gbp/photos", label: "Photos" },
    ] },
  ] },
  { id: "growth", href: "/growth", label: "Growth", desc: "More reviews, every week", icon: GrowthGlyph, group: "main", children: [
    { href: "/growth", label: "Goals", also: ["/growth/funnel"] },
    { href: "/gbp/cards", label: "Cards", tabs: [
      { href: "/gbp/cards", label: "Cards" }, { href: "/gbp/cards/designs", label: "Designs" }, { href: "/reputation/assistant", label: "Customer page", also: ["/reputation/assistant/settings"] },
    ] },
    { href: "/gbp/campaigns", label: "Campaigns", tabs: [
      { href: "/gbp/campaigns", label: "Campaigns" }, { href: "/gbp/campaigns/landing", label: "Page design" }, { href: "/gbp/campaigns/guide", label: "Guide" },
    ] },
    { href: "/growth/reports", label: "Reports" },
  ] },
  { id: "locations", href: "/gbp/locations", label: "Locations", desc: "Branches and Google connection", icon: LocationsGlyph, group: "tools", children: [
    { href: "/gbp/locations", label: "Locations" },
    { href: "/overview/locations", label: "Compare" },
  ] },
  { id: "whatsapp", href: "/whatsapp", label: "WhatsApp", desc: "Connect, customers, automations", icon: WhatsAppGlyph, group: "tools", flag: "whatsapp", children: [
    { href: "/whatsapp", label: "Overview" },
    { href: "/whatsapp/setup", label: "Set up" },
    { href: "/whatsapp/connect", label: "Connect" },
    { href: "/whatsapp/inbox", label: "Inbox" },
    { href: "/whatsapp/assistant", label: "Auto-reply" },
    { href: "/whatsapp/bookings", label: "Bookings" },
    { href: "/whatsapp/integrations", label: "Integrations" },
    { href: "/whatsapp/contacts", label: "Customers" },
    { href: "/whatsapp/optin", label: "Sign-ups" },
    { href: "/whatsapp/automations", label: "Automations" },
    { href: "/whatsapp/occasions", label: "Greetings" },
    { href: "/whatsapp/campaigns", label: "Offers" },
    { href: "/whatsapp/messages", label: "Messages" },
  ] },
  { id: "assistant", href: "/ai/today", label: "AI Assistant", desc: "Today's plan and helpers", icon: TodayGlyph, group: "assistant", children: [
    { href: "/ai/today", label: "Today" },
    { href: "/ai/automations", label: "Helpers" },
    { href: "/ai/studio", label: "Write a post" },
  ] },
  { id: "tasks", href: "/ai/tasks", label: "Tasks & Approvals", desc: "What waits for you", icon: TasksGlyph, group: "assistant", children: [
    { href: "/ai/tasks", label: "Tasks" },
    { href: "/ai/approvals", label: "Approvals" },
  ] },
  { id: "activity", href: "/ai/activity", label: "Activity", desc: "What the assistant did", icon: ActivityGlyph, group: "assistant" },
  { id: "settings", href: "/settings", label: "Settings", desc: "Business, team, alerts", icon: SettingsGlyph, group: "account", children: [
    { href: "/settings", label: "Business" },
    { href: "/settings/account", label: "Account" },
    { href: "/settings/team", label: "Team" },
    { href: "/settings/connections", label: "Connections" },
    { href: "/settings/notifications", label: "Notifications" },
    { href: "/settings/ai/voice", label: "AI & automation", also: ["/settings/ai"], tabs: [
      { href: "/settings/ai/voice", label: "Voice" }, { href: "/settings/ai/brain", label: "Brain" }, { href: "/settings/ai/autonomy", label: "Autonomy", only: ["owner", "admin"] }, { href: "/settings/ai/usage", label: "Usage", only: ["owner", "admin"] },
    ] },
    { href: "/settings/appearance", label: "Appearance" },
    { href: "/settings/audit", label: "Audit", only: ["owner", "admin"] },
  ] },
  { id: "billing", href: "/settings/billing", label: "Billing", desc: "Plan and payments", icon: BillingGlyph, group: "account", only: ["owner", "admin"], children: [
    { href: "/settings/billing", label: "Plan" },
    { href: "/settings/billing/payments", label: "Payments" },
  ] },
];

/** The four destinations on the phone's bottom bar, in order. The fifth, More, opens the sheet below. */
export const BOTTOM_IDS = ["home", "reviews", "seo", "growth"] as const;

export type MoreItem = { href: string; label: string; desc: string; icon: NavIcon; only?: Role[]; help?: boolean; flag?: "whatsapp" };
export const MORE_GROUPS: { label: string; items: MoreItem[] }[] = [
  { label: "Business", items: [
    { href: "/gbp/locations", label: "Locations", desc: "Branches and Google", icon: LocationsGlyph },
    { href: "/whatsapp", label: "WhatsApp", desc: "Connect, customers, automations", icon: WhatsAppGlyph, flag: "whatsapp" },
  ] },
  { label: "Assistant", items: [
    { href: "/ai/today", label: "AI Assistant", desc: "Today's plan and helpers", icon: TodayGlyph },
    { href: "/ai/tasks", label: "Tasks & Approvals", desc: "What waits for you", icon: TasksGlyph },
    { href: "/ai/activity", label: "Activity", desc: "What the assistant did", icon: ActivityGlyph },
  ] },
  { label: "Account", items: [
    { href: "/settings", label: "Settings", desc: "Business, team, alerts", icon: SettingsGlyph },
    { href: "/settings/billing", label: "Billing", desc: "Plan and payments", icon: BillingGlyph, only: ["owner", "admin"] },
    { href: "/help", label: "Help & Support", desc: "Search, or email us", icon: CircleHelp, help: true },
  ] },
];

export function navFor(role: Role | null, flags: NavFlags = {}): Dest[] {
  const ok = (only?: Role[]) => !only || (role !== null && only.includes(role));
  return DESTS.filter((d) => ok(d.only) && (!d.flag || flags[d.flag])).map((d) => (d.children ? { ...d, children: d.children.filter((c) => ok(c.only)).map((c) => (c.tabs ? { ...c, tabs: c.tabs.filter((t) => ok(t.only)) } : c)) } : d));
}
export const moreFor = (role: Role | null, flags: NavFlags = {}) => MORE_GROUPS.map((g) => ({ ...g, items: g.items.filter((i) => (!i.only || (role !== null && i.only.includes(role))) && (!i.flag || flags[i.flag])) }));

export type Located = { dest: Dest; child: Child | null; tab: Tab | null; detail: boolean };

const covers = (path: string, h: string) => path === h || path.startsWith(h + "/");
const hrefs = (d: Dest): { h: string; child: Child | null; tab: Tab | null }[] => [
  { h: d.href, child: null, tab: null },
  ...(d.also ?? []).map((h) => ({ h, child: null, tab: null })),
  ...(d.children ?? []).flatMap((c) => [
    { h: c.href, child: c, tab: null },
    ...(c.also ?? []).map((h) => ({ h, child: c, tab: null })),
    ...(c.tabs ?? []).flatMap((t) => [{ h: t.href, child: c, tab: t }, ...(t.also ?? []).map((h) => ({ h, child: c, tab: t }))]),
  ]),
];

/** Which destination, page and tab a path belongs to: the longest matching prefix wins. */
export function locate(path: string): Located | null {
  let best: { dest: Dest; child: Child | null; tab: Tab | null; len: number; exact: boolean } | null = null;
  for (const d of DESTS) for (const x of hrefs(d)) {
    if (covers(path, x.h) && (!best || x.h.length > best.len)) best = { dest: d, child: x.child, tab: x.tab, len: x.h.length, exact: path === x.h };
  }
  if (!best) return null;
  return { dest: best.dest, child: best.child ?? best.dest.children?.find((c) => c.href === best!.dest.href) ?? null, tab: best.tab, detail: !best.exact };
}

export function bottomActive(path: string): string {
  const l = locate(path);
  if (!l) return "more";
  return (BOTTOM_IDS as readonly string[]).includes(l.dest.id) ? l.dest.id : "more";
}

export const APP_PREFIXES = Array.from(new Set(["/admin", ...DESTS.flatMap((d) => hrefs(d).map((x) => x.h))]));
