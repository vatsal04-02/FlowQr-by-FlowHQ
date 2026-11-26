import { Sparkles } from "lucide-react";
import type { ComponentType } from "react";
import { GbpIcon } from "@/components/icons/Gbp";
import { HomeGlyph, SettingsGlyph } from "@/components/icons/Nav";
import { allows, featureFor, type PlanFeatures } from "./nav-features";
import type { Role } from "./types";

/** One of FlowQR's own glyphs (components/icons/Nav.tsx), a brand mark (GBP), or a lucide icon: all take the same props. */
export type NavIcon = ComponentType<{ className?: string; strokeWidth?: number; "aria-hidden"?: boolean | "true" | "false" }>;

/**
 * One navigation system for the whole app (docs/DESIGN.md). Four places, and nothing else to choose from: Home (how am I doing), AI (what the assistant does and how it behaves),
 * Google (everything about how you show up and are reviewed on Google) and Settings (the business, the team, billing). Phones: a bottom bar with those four. Tablet and desktop: one left
 * sidebar with the same four, the pages of the current place folding open underneath it. Both read this file, so a page is added or renamed in exactly one place.
 * Every old URL keeps working through legacy-routes.mjs. Pages for unfinished integrations (Studio calendar, brand kit, assets, social) are deliberately not listed.
 */
export type Tab = { href: string; label: string; also?: string[]; only?: Role[] };
export type Child = {
  href: string; label: string;
  /** other paths that belong to this page (detail pages, old pages) so the right tab stays highlighted */
  also?: string[];
  /** a second row for pages that share a theme */
  tabs?: Tab[];
  only?: Role[];
  flag?: "whatsapp";
};
export type Group = "main" | "account";
export type Dest = { id: string; href: string; label: string; short?: string; desc: string; icon: NavIcon; group: Group; children?: Child[]; also?: string[]; only?: Role[]; flag?: "whatsapp" };
/** Server switches that show or hide a destination or a page of one (me.integrations). A switched-off feature has no menu entry at all. */
export type NavFlags = { whatsapp?: boolean };

/** The sidebar sections, in order. Home, AI and Google sit together; Settings is set apart at the bottom. Neither has a heading: four items need none. */
export const GROUPS: Group[] = ["main", "account"];
export const GROUP_LABEL: Record<Group, string | null> = { main: null, account: null };

export const DESTS: Dest[] = [
  { id: "home", href: "/overview", label: "Home", desc: "Growth score and this week's moves", icon: HomeGlyph, group: "main" },
  { id: "ai", href: "/ai/today", label: "AI", desc: "Your assistant: plan, approvals, studio, WhatsApp and its settings", icon: Sparkles, group: "main", children: [
    { href: "/ai/today", label: "Today", tabs: [
      { href: "/ai/today", label: "Plan" }, { href: "/ai/automations", label: "Helpers" }, { href: "/ai/operator", label: "AI Operator" },
    ] },
    { href: "/gbp/studio", label: "Studio", also: ["/gbp/studio/new"], tabs: [
      { href: "/gbp/studio", label: "Campaigns", also: ["/gbp/studio/new"] }, { href: "/ai/studio", label: "Write a post" },
    ] },
    { href: "/ai/tasks", label: "To review", tabs: [
      { href: "/ai/tasks", label: "Tasks" }, { href: "/ai/approvals", label: "Approvals" }, { href: "/ai/changes", label: "Changes" },
    ] },
    { href: "/ai/activity", label: "Activity" },
    { href: "/whatsapp", label: "WhatsApp", flag: "whatsapp", tabs: [
      { href: "/whatsapp", label: "Overview" },
      { href: "/whatsapp/setup", label: "Set up" },
      { href: "/whatsapp/connect", label: "Connect" },
      { href: "/whatsapp/inbox", label: "Inbox" },
      { href: "/whatsapp/assistant", label: "Auto-reply" },
      { href: "/whatsapp/bookings", label: "Bookings" },
      { href: "/whatsapp/integrations", label: "Integrations" },
      { href: "/whatsapp/ads", label: "Ad sources" },
      { href: "/whatsapp/contacts", label: "Customers" },
      { href: "/whatsapp/optin", label: "Sign-ups" },
      { href: "/whatsapp/automations", label: "Automations" },
      { href: "/whatsapp/occasions", label: "Greetings" },
      { href: "/whatsapp/campaigns", label: "Offers" },
      { href: "/whatsapp/messages", label: "Messages" },
    ] },
    { href: "/ai/settings/voice", label: "AI settings", also: ["/ai/settings"], tabs: [
      { href: "/ai/settings/voice", label: "Voice" }, { href: "/ai/settings/brain", label: "Brain" },
      { href: "/ai/settings/autonomy", label: "Autonomy", only: ["owner", "admin"] }, { href: "/ai/settings/usage", label: "Usage", only: ["owner", "admin"] },
    ] },
  ] },
  { id: "google", href: "/seo", label: "Google", desc: "Reviews, rankings, your profile, posts, photos and locations", icon: GbpIcon, group: "main", children: [
    { href: "/seo", label: "Overview" },
    { href: "/gbp/reviews", label: "Reviews", tabs: [
      { href: "/gbp/reviews", label: "Inbox" }, { href: "/reputation/drafts", label: "Drafts" }, { href: "/reputation/insights", label: "Insights" },
    ] },
    { href: "/seo/rankings", label: "Search", also: ["/seo/searches", "/seo/competitors"], tabs: [
      { href: "/seo/rankings", label: "Rankings", also: ["/seo/searches", "/seo/competitors"] }, { href: "/seo/performance", label: "Performance" },
    ] },
    { href: "/seo/profile", label: "Profile", tabs: [
      { href: "/seo/profile", label: "Checklist" }, { href: "/gbp/info", label: "Info", also: ["/gbp/hours"] }, { href: "/gbp/posts", label: "Posts" }, { href: "/gbp/photos", label: "Photos" },
    ] },
    { href: "/growth", label: "Get reviews", also: ["/growth/funnel"], tabs: [
      { href: "/growth", label: "Goals", also: ["/growth/funnel"] }, { href: "/gbp/cards", label: "Cards" }, { href: "/gbp/cards/designs", label: "Designs" },
      { href: "/reputation/assistant", label: "Customer page", also: ["/reputation/assistant/settings"] },
      { href: "/gbp/campaigns", label: "Campaigns" }, { href: "/gbp/campaigns/landing", label: "Page design" }, { href: "/gbp/campaigns/guide", label: "Guide" }, { href: "/growth/reports", label: "Reports" },
    ] },
    { href: "/gbp/locations", label: "Locations", tabs: [
      { href: "/gbp/locations", label: "Locations" }, { href: "/overview/locations", label: "Compare" },
    ] },
  ] },
  { id: "settings", href: "/settings", label: "Settings", desc: "Business, team, billing, alerts and help", icon: SettingsGlyph, group: "account" },
];

/** The destinations on the phone's bottom bar, in order. There is no fifth: nothing is hidden behind a More menu. */
export const BOTTOM_IDS = ["home", "ai", "google", "settings"] as const;

export function navFor(role: Role | null, flags: NavFlags = {}, features?: PlanFeatures): Dest[] {
  const ok = (only?: Role[]) => !only || (role !== null && only.includes(role));
  const out: Dest[] = [];
  for (const d of DESTS) {
    if (!ok(d.only) || (d.flag && !flags[d.flag])) continue;
    if (!d.children) { if (allows(features, d.href)) out.push(d); continue; }
    // a page shows when this person's role, the server's switches and the plan allow it; a page with tabs opens on its first tab the plan includes
    const children = d.children
      .filter((c) => ok(c.only) && (!c.flag || flags[c.flag]))
      .map((c): Child | null => {
        if (!c.tabs) return allows(features, c.href) ? c : null;
        const tabs = c.tabs.filter((t) => ok(t.only) && allows(features, t.href));
        if (!tabs.length) return null;
        return { ...c, href: tabs.some((t) => t.href === c.href) ? c.href : tabs[0].href, tabs };
      })
      .filter((c): c is Child => c !== null);
    if (!children.length) continue;   // every page of this destination is outside the plan: the destination is not shown at all
    // the destination opens on its first page the plan includes
    out.push({ ...d, href: children.some((c) => c.href === d.href) ? d.href : children[0].href, children });
  }
  return out;
}

/** The plan feature the page at this path needs (null: every plan has it). Used to show "not in your plan" instead of a page that would only fail. */
export function requiredFeature(path: string): string | null {
  const l = locate(path);
  return l ? featureFor(l.tab?.href, l.child?.href, l.dest.href) : null;
}

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

/** Which bottom-bar item a path belongs to; "" for a page outside the four (nothing is highlighted). */
export function bottomActive(path: string): string {
  const l = locate(path);
  return l && (BOTTOM_IDS as readonly string[]).includes(l.dest.id) ? l.dest.id : "";
}

export const APP_PREFIXES = Array.from(new Set(["/admin", ...DESTS.flatMap((d) => hrefs(d).map((x) => x.h))]));
