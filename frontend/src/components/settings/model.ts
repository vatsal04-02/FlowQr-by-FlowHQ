import { Bell, Building2, CreditCard, Database, Globe, History, Link2, MapPin, MessageCircle, Palette, Receipt, Share2, Sparkles, User, Users } from "lucide-react";
import type { NavIcon } from "@/lib/nav";
import type { Role } from "@/lib/types";

/**
 * The one place that says what is in Settings and where it lives (docs/DESIGN_SETTINGS_MOBILE.md §5): six groups, then pages. Two levels only.
 * The phone hub, the laptop menu, the search box and the Ctrl K palette all read this list, so a page is added or renamed once.
 * `status` names a live chip (see useSettingsStatus); a row without one shows its subtitle (what you can do or see there, under 40 characters).
 */
export type GroupId = "account" | "business" | "connect" | "prefs" | "billing" | "security";
export type StatusKey = "google" | "plan" | "whatsapp" | "meta";
export type SettingsRow = { id: string; href: string; title: string; sub: string; icon: NavIcon; group: GroupId; only?: Role[]; status?: StatusKey; also?: string[] };

export const GROUPS: { id: GroupId; label: string; action?: { label: string; href: string } }[] = [
  { id: "account", label: "Your account" },
  { id: "business", label: "Business" },
  { id: "connect", label: "Connected accounts", action: { label: "See all", href: "/settings/connections" } },
  { id: "prefs", label: "Preferences" },
  { id: "billing", label: "Billing" },
  { id: "security", label: "Security & activity" },
];

export const ROWS: SettingsRow[] = [
  { id: "account", href: "/settings/account", title: "Profile and password", sub: "Your name, email and sign-in", icon: User, group: "account" },

  { id: "business", href: "/settings/business", title: "Business profile", sub: "Name, category, contact, logo", icon: Building2, group: "business" },
  { id: "locations", href: "/gbp/locations", title: "Locations", sub: "Branches, review links, cards", icon: MapPin, group: "business" },
  { id: "team", href: "/settings/team", title: "Team", sub: "Who can sign in, and what they see", icon: Users, group: "business" },

  { id: "google", href: "/settings/connections/google", title: "Google Business Profile", sub: "Reviews, replies and your profile", icon: Link2, group: "connect", status: "google", also: ["/gbp/connect"] },
  { id: "whatsapp", href: "/whatsapp/connect", title: "WhatsApp Business", sub: "Customer chats and messages", icon: MessageCircle, group: "connect", status: "whatsapp" },
  { id: "meta", href: "/settings/connections", title: "Facebook and Instagram", sub: "Posting to your pages", icon: Share2, group: "connect", status: "meta" },

  { id: "notifications", href: "/settings/notifications", title: "Notifications", sub: "Which emails you get", icon: Bell, group: "prefs" },
  { id: "ai", href: "/settings/ai/voice", title: "AI and brand voice", sub: "How replies and posts sound", icon: Sparkles, group: "prefs", also: ["/settings/ai"] },
  { id: "appearance", href: "/settings/appearance", title: "Appearance", sub: "Light or dark", icon: Palette, group: "prefs" },
  { id: "region", href: "/settings/region", title: "Language and time zone", sub: "Language, dates, time zone", icon: Globe, group: "prefs" },

  { id: "plan", href: "/settings/billing", title: "Plan", sub: "Your plan and what it includes", icon: CreditCard, group: "billing", only: ["owner", "admin"], status: "plan" },
  { id: "payments", href: "/settings/billing/payments", title: "Payments and card orders", sub: "Receipts and printed cards", icon: Receipt, group: "billing", only: ["owner", "admin"] },

  { id: "audit", href: "/settings/audit", title: "Audit log", sub: "Who did what, and when", icon: History, group: "security", only: ["owner", "admin"] },
  { id: "data", href: "/settings/data", title: "Your data", sub: "Export or delete your data", icon: Database, group: "security" },
];

/** The rows this person may open. WhatsApp is listed only while the server has it switched on (same switch as the sidebar). */
export const rowsFor = (role: Role | null, flags: { whatsapp?: boolean } = {}) => ROWS.filter((r) => (!r.only || (role !== null && r.only.includes(role))) && (r.id !== "whatsapp" || !!flags.whatsapp));

const covers = (path: string, h: string) => path === h || path.startsWith(h + "/");
/** The row a path belongs to (the longest matching address wins, so /settings/billing/payments is Payments, not Plan). */
export function rowAt(path: string, rows: SettingsRow[] = ROWS): SettingsRow | null {
  let best: SettingsRow | null = null, len = -1;
  for (const r of rows) for (const h of [r.href, ...(r.also ?? [])]) if (covers(path, h) && h.length > len) { best = r; len = h.length; }
  return best;
}

/** Search over what the person can read on a row. Empty search matches nothing (the hub shows the groups instead). */
export function searchRows(rows: SettingsRow[], q: string): SettingsRow[] {
  const t = q.trim().toLowerCase();
  if (!t) return [];
  const label = (g: GroupId) => GROUPS.find((x) => x.id === g)?.label ?? "";
  return rows.filter((r) => `${r.title} ${r.sub} ${label(r.group)}`.toLowerCase().includes(t));
}
