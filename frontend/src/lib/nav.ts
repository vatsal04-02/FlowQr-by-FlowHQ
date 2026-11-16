import {
  Activity, BarChart3, Bell, Brain, Building2, CreditCard, Crosshair, FileText, Gauge, HeartPulse, LayoutGrid, ListChecks, Megaphone, MessageSquare,
  Palette, Plug, QrCode, ScrollText, Search, Settings2, ShieldCheck, Sparkles, Star, SunMoon, TrendingUp, UserRound, Users, type LucideIcon,
} from "lucide-react";
import type { Role } from "./types";

export type SubTab = { href: string; label: string; /** only these roles see this tab (the API enforces access either way) */ only?: Role[] };
export type Item = {
  href: string; label: string;
  /** one short line under the label in the rail flyout and the command palette */
  desc: string; icon: LucideIcon;
  /** other paths that belong to this item (detail pages, legacy URLs), so the right item stays highlighted */
  also?: string[];
  /** pages that share this item: shown as small pills above the page, so related pages sit together */
  sub?: SubTab[];
  /** only these roles see it in the navigation (hiding is a convenience; the API enforces access) */
  only?: Role[];
};
export type SectionId = "workspace" | "reputation" | "seo" | "analytics" | "ai" | "settings";
export type Section = { id: SectionId; label: string; /** the label on the phone's bottom bar, where six sections share one row */ short: string; icon: LucideIcon; items: Item[] };

/**
 * The app in six sections (docs/LOCAL_SEO_ARCHITECTURE_PROPOSAL.md §2, approved for Phase 2): the top pill nav picks a section, the left rail (and the chip row on phones) picks a
 * page in it. Every URL the app ever had keeps working through LEGACY_ROUTES (legacy-routes.mjs, served as permanent redirects), so bookmarks, emails and printed links survive.
 *
 * Pages for unfinished integrations (the five WhatsApp inbox pages, the four Content Studio pages for Meta) are deliberately NOT listed here. Their routes and source still exist
 * and they still say "Setup required" if opened by URL, but navigation never advertises something that does not work.
 */
export const NAV: Section[] = [
  { id: "workspace", label: "Workspace", short: "Home", icon: LayoutGrid, items: [
    { href: "/overview", label: "Overview", desc: "Your business at a glance", icon: LayoutGrid },
    { href: "/gbp/locations", label: "Locations", desc: "Connect Google, compare branches", icon: Building2,
      sub: [{ href: "/gbp/locations", label: "Locations & Google" }, { href: "/overview/locations", label: "Compare branches" }] },
  ] },
  { id: "reputation", label: "Reputation", short: "Reviews", icon: Star, items: [
    { href: "/gbp/reviews", label: "Reviews & Inbox", desc: "Read, reply, approve and publish", icon: MessageSquare,
      sub: [{ href: "/gbp/reviews", label: "Reviews" }, { href: "/reputation/drafts", label: "Reply drafts" }, { href: "/reputation/insights", label: "Insights" }] },
    { href: "/gbp/cards", label: "Review Collection", desc: "QR/NFC cards and the customer review page", icon: QrCode,
      sub: [{ href: "/gbp/cards", label: "Cards" }, { href: "/gbp/cards/designs", label: "Designs & export" }, { href: "/reputation/assistant", label: "Review-writing assistant" }] },
    { href: "/gbp/campaigns", label: "Campaigns", desc: "Landing pages that ask for reviews", icon: Megaphone,
      sub: [{ href: "/gbp/campaigns", label: "Campaigns" }, { href: "/gbp/campaigns/landing", label: "Landing pages" }, { href: "/gbp/campaigns/guide", label: "Setup guide" }] },
  ] },
  { id: "seo", label: "Local SEO", short: "SEO", icon: Search, items: [
    { href: "/seo", label: "SEO Overview", desc: "How visible you are in local search", icon: Search },
    { href: "/seo/rank", label: "Local Rank Tracking", desc: "Where you appear for key searches", icon: TrendingUp },
    { href: "/seo/profile", label: "Google Profile Health", desc: "What to fix on your Google profile", icon: HeartPulse,
      sub: [{ href: "/seo/profile", label: "Health" }, { href: "/gbp/info", label: "Business info" }, { href: "/gbp/hours", label: "Opening hours" }, { href: "/gbp/posts", label: "Posts" }, { href: "/gbp/photos", label: "Photos" }] },
    { href: "/seo/competitors", label: "Competitor Analysis", desc: "Who appears next to you", icon: Crosshair },
  ] },
  { id: "analytics", label: "Analytics", short: "Analytics", icon: BarChart3, items: [
    { href: "/analytics/performance", label: "Performance", desc: "Google views and actions, reviews, cards", icon: Gauge,
      sub: [{ href: "/analytics/performance", label: "Search & Maps" }, { href: "/analytics/reviews", label: "Reviews" }, { href: "/analytics/funnel", label: "Cards" }, { href: "/analytics/campaigns", label: "Review campaigns" }] },
    { href: "/analytics/reports", label: "Reports", desc: "PDF and CSV exports", icon: FileText },
  ] },
  { id: "ai", label: "AI Growth", short: "AI", icon: Sparkles, items: [
    { href: "/ai/today", label: "Growth Assistant", desc: "Today's plan and automations", icon: Sparkles,
      sub: [{ href: "/ai/today", label: "Today" }, { href: "/ai/automations", label: "Automations" }] },
    { href: "/ai/tasks", label: "Tasks", desc: "Recommendations with the data behind them", icon: ListChecks },
    { href: "/ai/approvals", label: "Approvals", desc: "Everything waiting for a person", icon: ShieldCheck },
    { href: "/ai/activity", label: "Activity", desc: "What the assistant did and what failed", icon: Activity },
    { href: "/ai/studio", label: "Content Studio", desc: "Write post captions with AI", icon: Palette },
  ] },
  { id: "settings", label: "Settings", short: "Settings", icon: Settings2, items: [
    { href: "/settings", label: "Business", desc: "Public details, your data", icon: Building2 },
    { href: "/settings/account", label: "Account", desc: "Profile, sign-in, password", icon: UserRound },
    { href: "/settings/team", label: "Team", desc: "Roles and invites", icon: Users },
    { href: "/settings/billing", label: "Billing", desc: "Plan, subscription, payments", icon: CreditCard, only: ["owner", "admin"],
      sub: [{ href: "/settings/billing", label: "Plan" }, { href: "/settings/billing/payments", label: "Payments & orders" }] },
    { href: "/settings/connections", label: "Connections", desc: "Google, WhatsApp, social", icon: Plug },
    { href: "/settings/notifications", label: "Notifications", desc: "Email alerts", icon: Bell },
    { href: "/settings/ai/voice", label: "AI & Automation", desc: "Voice, knowledge, autonomy, usage", icon: Brain, also: ["/settings/ai"],
      sub: [{ href: "/settings/ai/voice", label: "Brand voice" }, { href: "/settings/ai/brain", label: "Business brain" },
        { href: "/settings/ai/autonomy", label: "Autonomy", only: ["owner", "admin"] }, { href: "/settings/ai/usage", label: "Usage & limits", only: ["owner", "admin"] }] },
    { href: "/settings/appearance", label: "Appearance", desc: "Light, dark, system", icon: SunMoon },
    { href: "/settings/audit", label: "Audit", desc: "Who changed what", icon: ScrollText, only: ["owner", "admin"] },
  ] },
];

export const sectionHref = (s: Section) => s.items[0].href;

/** The navigation as this person sees it: pages for other roles are left out (PRD §6.5 "hide, don't just disable"). */
export function navFor(role: Role | null): Section[] {
  const ok = (only?: Role[]) => !only || (role !== null && only.includes(role));
  return NAV.map((s) => ({ ...s, items: s.items.filter((i) => ok(i.only)).map((i) => (i.sub ? { ...i, sub: i.sub.filter((t) => ok(t.only)) } : i)) }));
}

export type Located = { section: Section; item: Item; sub: SubTab | null; detail: boolean };

const paths = (t: Item) => [t.href, ...(t.also ?? []), ...(t.sub ?? []).map((s) => s.href)];
const covers = (path: string, h: string) => path === h || path.startsWith(h + "/");

/** Which section, item and sub-page a path belongs to: the longest matching prefix wins, so /cards/analytics never lights up "QR/NFC cards". */
export function locate(path: string): Located | null {
  let best: { section: Section; item: Item; len: number } | null = null;
  for (const section of NAV) for (const item of section.items) for (const h of paths(item)) {
    if (covers(path, h) && (!best || h.length > best.len)) best = { section, item, len: h.length };
  }
  if (!best) return null;
  const sub = (best.item.sub ?? []).filter((s) => covers(path, s.href)).sort((a, b) => b.href.length - a.href.length)[0] ?? null;
  const exact = paths(best.item).some((h) => h === path);
  return { section: best.section, item: best.item, sub, detail: !exact };
}

/** Every path the app shell serves, for the no-flash theme script in the root layout (it must not touch marketing pages). */
export const APP_PREFIXES = Array.from(new Set(["/admin", ...NAV.flatMap((s) => s.items.flatMap(paths))]));
