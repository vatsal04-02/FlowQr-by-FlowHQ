import {
  Activity, BarChart3, BookOpen, Bot, Brush, CalendarDays, CheckCheck, CreditCard, FileText, Globe, Image as ImageIcon, Inbox, LayoutDashboard, Lightbulb,
  Link2, ListChecks, MapPin, MapPinned, MessageCircle, Megaphone, Palette, PenLine, QrCode, ScrollText, Send, Settings, ShieldCheck, Sparkles, Star, Store,
  TrendingUp, Users, Wand2, Workflow, Zap,
} from "lucide-react";

export type NavItem = {
  href: string; label: string; icon: typeof Star;
  /** other paths that belong under this entry (detail pages, legacy URLs) so the right item stays highlighted */
  also?: string[];
};
export type NavGroup = { id: string; title: string; icon: typeof Star; href?: string; items: NavItem[] };

/** The one navigation tree. Existing URLs are kept, so nothing bookmarked moves; new pages are added under the groups below. */
export const NAV: NavGroup[] = [
  { id: "overview", title: "Business Overview", icon: LayoutDashboard, href: "/dashboard", items: [] },
  { id: "google", title: "Google Business", icon: Store, items: [
    { href: "/google", label: "Overview", icon: Link2 },
    { href: "/profile", label: "Profile Manager", icon: PenLine },
    { href: "/reviews", label: "Reviews", icon: Star },
    { href: "/posts", label: "Posts", icon: Megaphone },
    { href: "/media", label: "Photos & Media", icon: ImageIcon },
    { href: "/performance", label: "Performance", icon: TrendingUp },
    { href: "/local-visibility", label: "Local Visibility", icon: MapPinned },
  ] },
  { id: "agent", title: "AI Growth Agent", icon: Bot, items: [
    { href: "/agent", label: "Daily Plan", icon: ListChecks },
    { href: "/agent/recommendations", label: "Recommendations", icon: Lightbulb },
    { href: "/agent/approvals", label: "Approvals", icon: CheckCheck },
    { href: "/agent/activity", label: "Activity", icon: Activity },
    { href: "/agent/knowledge", label: "Knowledge Base", icon: BookOpen },
    { href: "/agent/automations", label: "Automations", icon: Workflow },
  ] },
  { id: "studio", title: "Content Studio", icon: Wand2, items: [
    { href: "/studio", label: "AI Creator", icon: Sparkles },
    { href: "/studio/calendar", label: "Calendar", icon: CalendarDays },
    { href: "/studio/brand", label: "Brand Kit", icon: Palette },
    { href: "/studio/assets", label: "Asset Library", icon: ImageIcon },
    { href: "/studio/social", label: "Social Publishing", icon: Send },
  ] },
  { id: "growth", title: "Review Growth", icon: QrCode, items: [
    { href: "/review-growth/campaigns", label: "QR Campaigns", icon: QrCode, also: ["/review-growth"] },
    { href: "/cards", label: "Cards", icon: Zap },
    { href: "/qr", label: "QR design & export", icon: Brush },
    { href: "/review-growth/customize", label: "Landing page", icon: Palette },
    { href: "/review-growth/generator", label: "AI Review Assistant", icon: Sparkles, also: ["/review-growth/settings"] },
    { href: "/review-growth/analytics", label: "Analytics", icon: BarChart3 },
  ] },
  { id: "inbox", title: "Inbox & Leads", icon: Inbox, items: [
    { href: "/inbox", label: "WhatsApp Inbox", icon: MessageCircle },
    { href: "/inbox/leads", label: "Leads", icon: Users },
    { href: "/inbox/appointments", label: "Appointments", icon: CalendarDays },
    { href: "/inbox/followups", label: "Follow-ups", icon: ScrollText },
    { href: "/inbox/campaigns", label: "Campaigns", icon: Megaphone },
  ] },
  { id: "reports", title: "Reports", icon: FileText, href: "/reports", items: [] },
  { id: "settings", title: "Settings", icon: Settings, items: [
    { href: "/settings", label: "Business & account", icon: Settings },
    { href: "/settings/connections", label: "Connections", icon: Globe },
    { href: "/locations", label: "Locations", icon: MapPin },
    { href: "/staff", label: "Team & permissions", icon: Users },
    { href: "/settings/ai", label: "AI usage & limits", icon: Bot },
    { href: "/subscription", label: "Billing", icon: CreditCard, also: ["/payments"] },
    { href: "/settings/audit", label: "Audit log", icon: ShieldCheck },
  ] },
];

/** Paths that belong under a group/item even though they are not entries (legacy analytics pages live under Reports). */
const REPORT_ALIASES = ["/analytics", "/cards/analytics"];

export type Located = { group: NavGroup; item: NavItem | null; detail: boolean };

/** The nav location of a path: the entry with the longest matching prefix wins, so /cards/analytics never lights up "Cards". */
export function locate(path: string): Located | null {
  if (REPORT_ALIASES.some((a) => path === a || path.startsWith(a + "/"))) return { group: NAV.find((g) => g.id === "reports")!, item: null, detail: path !== "/analytics" && path !== "/cards/analytics" };
  let best: { group: NavGroup; item: NavItem | null; len: number; exact: boolean } | null = null;
  for (const g of NAV) {
    const entries: (NavItem | { href: string; also?: string[] })[] = g.items.length ? g.items : g.href ? [{ href: g.href }] : [];
    for (const it of entries) {
      for (const h of [it.href, ...(it.also ?? [])]) {
        if (path === h || path.startsWith(h + "/")) {
          if (!best || h.length > best.len) best = { group: g, item: g.items.find((x) => x.href === it.href) ?? null, len: h.length, exact: path === h };
        }
      }
    }
  }
  return best ? { group: best.group, item: best.item, detail: !best.exact } : null;
}

export const isEntryActive = (path: string, href: string) => {
  const l = locate(path);
  return !!l && (l.item?.href === href || (l.item === null && l.group.href === href));
};

/** Items shown in the phone tab bar. */
export const TAB_HREFS = ["/dashboard", "/reviews", "/agent", "/cards"];
