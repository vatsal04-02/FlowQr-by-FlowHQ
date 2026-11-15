import {
  BarChart3, Bell, Brain, Building2, CreditCard, FileText, Filter, Gauge, Image, Inbox, LayoutGrid, Lightbulb, Link2, ListChecks, MapPin,
  Megaphone, MessageSquare, Palette, PenLine, Plug, QrCode, ScrollText, Settings2, SlidersHorizontal, Sparkles, Star, Store, SunMoon,
  ShieldCheck, TrendingUp, UserRound, Users, type LucideIcon,
} from "lucide-react";
import type { Role } from "./types";

export type SubTab = { href: string; label: string };
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
export type SectionId = "overview" | "gbp" | "ai" | "settings";
export type Section = { id: SectionId; label: string; icon: LucideIcon; items: Item[] };

/**
 * The app in four sections (docs PRD §5): the top pill nav picks a section, the left rail (and the chip row on phones) picks a page in it.
 * URLs follow the sections (/overview, /gbp, /ai, /settings). Every old URL redirects permanently (LEGACY_ROUTES below, PRD §8), so
 * bookmarks, emails and printed links keep working.
 */
export const NAV: Section[] = [
  { id: "overview", label: "Overview", icon: LayoutGrid, items: [
    { href: "/overview", label: "Summary", desc: "Everything at a glance", icon: LayoutGrid },
    { href: "/overview/reviews", label: "Reviews", desc: "Ratings, volume, reply speed", icon: Star },
    { href: "/overview/performance", label: "Search & Maps", desc: "Views, calls, directions", icon: MapPin },
    { href: "/overview/funnel", label: "Customer funnel", desc: "Scans to Google clicks", icon: Filter,
      sub: [{ href: "/overview/funnel", label: "Cards" }, { href: "/overview/campaigns", label: "Review campaigns" }] },
    { href: "/overview/locations", label: "Locations", desc: "Compare branches", icon: Building2 },
    { href: "/overview/reports", label: "Reports", desc: "PDF and CSV exports", icon: BarChart3 },
  ] },
  { id: "gbp", label: "GBP Manager", icon: Store, items: [
    { href: "/gbp", label: "Overview", desc: "All six Google tools at a glance", icon: LayoutGrid },
    { href: "/gbp/reviews", label: "Reviews & replies", desc: "Inbox, approve and publish", icon: MessageSquare },
    { href: "/gbp/info", label: "Business info", desc: "Description, category, hours", icon: Store,
      sub: [{ href: "/gbp/info", label: "Business info" }, { href: "/gbp/hours", label: "Opening hours" }] },
    { href: "/gbp/posts", label: "Posts", desc: "Updates on your profile", icon: FileText },
    { href: "/gbp/photos", label: "Photos", desc: "Add and organise photos", icon: Image },
    { href: "/gbp/rank", label: "Local ranking", desc: "Where you appear for key searches", icon: TrendingUp },
    { href: "/gbp/locations", label: "Locations & Google", desc: "Connection and sync", icon: Link2 },
    { href: "/gbp/cards", label: "QR/NFC cards", desc: "Assign, print, track", icon: QrCode,
      sub: [{ href: "/gbp/cards", label: "Cards" }, { href: "/gbp/cards/designs", label: "Designs & export" }] },
    { href: "/gbp/campaigns", label: "Review campaigns", desc: "Landing pages that ask for reviews", icon: Megaphone,
      sub: [{ href: "/gbp/campaigns", label: "Campaigns" }, { href: "/gbp/campaigns/landing", label: "Landing pages" }, { href: "/gbp/campaigns/guide", label: "Setup guide" }] },
    { href: "/gbp/inbox", label: "Inbox & leads", desc: "Messages, leads, follow-ups", icon: Inbox,
      sub: [{ href: "/gbp/inbox", label: "WhatsApp inbox" }, { href: "/gbp/inbox/leads", label: "Leads" }, { href: "/gbp/inbox/appointments", label: "Appointments" },
        { href: "/gbp/inbox/followups", label: "Follow-ups" }, { href: "/gbp/inbox/campaigns", label: "Campaigns" }] },
  ] },
  { id: "ai", label: "AI", icon: Sparkles, items: [
    { href: "/ai", label: "Reply assistant", desc: "Drafts waiting for approval", icon: Sparkles },
    { href: "/ai/today", label: "AI assistant", desc: "Today's plan, tasks, automations", icon: ListChecks,
      sub: [{ href: "/ai/today", label: "Today" }, { href: "/ai/tasks", label: "Tasks" }, { href: "/ai/approvals", label: "Waiting for approval" },
        { href: "/ai/activity", label: "Activity" }, { href: "/ai/automations", label: "Automations" }] },
    { href: "/ai/autonomy", label: "Autonomy", desc: "What FlowQR may do on its own", icon: ShieldCheck, only: ["owner", "admin"] },
    { href: "/ai/voice", label: "Brand voice", desc: "Tone and instructions", icon: SlidersHorizontal },
    { href: "/ai/assistant", label: "Review-writing assistant", desc: "What customers see", icon: PenLine,
      sub: [{ href: "/ai/assistant", label: "Preview" }, { href: "/ai/assistant/settings", label: "Settings" }] },
    { href: "/ai/insights", label: "Insights", desc: "Topics and sentiment", icon: Lightbulb },
    { href: "/ai/studio", label: "Content studio", desc: "Posts, calendar, brand kit", icon: Palette,
      sub: [{ href: "/ai/studio", label: "AI Creator" }, { href: "/ai/studio/calendar", label: "Calendar" }, { href: "/ai/studio/brand", label: "Brand Kit" },
        { href: "/ai/studio/assets", label: "Asset Library" }, { href: "/ai/studio/social", label: "Social publishing" }] },
    { href: "/ai/brain", label: "Business brain", desc: "What the AI knows about you", icon: Brain },
    { href: "/ai/usage", label: "Usage & limits", desc: "Monthly AI usage", icon: Gauge, only: ["owner", "admin"] },
  ] },
  { id: "settings", label: "Settings", icon: Settings2, items: [
    { href: "/settings", label: "Business", desc: "Public details, your data", icon: Building2 },
    { href: "/settings/team", label: "Team", desc: "Roles and invites", icon: Users },
    { href: "/settings/billing", label: "Plan & billing", desc: "Subscription, payments", icon: CreditCard, only: ["owner", "admin"],
      sub: [{ href: "/settings/billing", label: "Plan" }, { href: "/settings/billing/payments", label: "Payments & orders" }] },
    { href: "/settings/account", label: "Account", desc: "Profile, sign-in, password", icon: UserRound },
    { href: "/settings/connections", label: "Connections", desc: "Google, WhatsApp, social", icon: Plug },
    { href: "/settings/appearance", label: "Appearance", desc: "Light, dark, system", icon: SunMoon },
    { href: "/settings/notifications", label: "Notifications", desc: "Email alerts", icon: Bell },
    { href: "/settings/audit", label: "Audit log", desc: "Who changed what", icon: ScrollText, only: ["owner", "admin"] },
  ] },
];

export const sectionHref = (s: Section) => s.items[0].href;

/** The navigation as this person sees it: pages for other roles are left out (PRD §6.5 "hide, don't just disable"). */
export function navFor(role: Role | null): Section[] {
  return NAV.map((s) => ({ ...s, items: s.items.filter((i) => !i.only || (role !== null && i.only.includes(role))) }));
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
