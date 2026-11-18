// Website builder: the shapes the admin editor works with, and the small pure helpers it uses. The server is the source of truth for every rule (limits, allowed links, which sections a template
// has): the editor draws its forms from GET /admin/sites/templates and shows the server's messages. Nothing here validates business content.

export interface FieldSpec {
  key: string; label: string; kind: "text" | "textarea" | "phone" | "email" | "url" | "asset" | "select" | "bool" | "list" | "strings";
  max?: number; required?: boolean; hint?: string | null; options?: string[]; fields?: FieldSpec[]; max_items?: number; link?: string;
}
export interface SectionTypeSpec { label: string; fields: FieldSpec[] }
export interface TemplateInfo { key: string; label: string; description: string; version: number; accent: string; hero: string; sections: string[]; allowed_sections: string[] }
export interface Catalogue {
  templates: TemplateInfo[]; section_types: Record<string, SectionTypeSpec>; business_fields: FieldSpec[]; accents: Record<string, string>; cta_kinds: string[]; days: string[]; max_sections: number;
}
export interface Section { id: string; type: string; enabled: boolean; data: Record<string, unknown> }
export interface Hours { day: string; closed: boolean; open: string; close: string }
export interface Cta { kind: string; label: string }
export interface SiteContent {
  business: Record<string, unknown> & { hours: Hours[] };
  cta: { primary: Cta; secondary: Cta | null };
  seo: { title: string; description: string; og_image: string | null };
  theme: { accent: string };
  sections: Section[];
}
export interface SiteAssetInfo { id: string; kind: string; width: number; height: number; size_bytes: number; alt_text: string; sort_order: number }
export interface Blocker { path: string; message: string }
export interface SiteInfo {
  id: string; tenant_id: string; site_slug: string; hostname: string; url: string; template_key: string; template_version: number; status: "draft" | "published" | "unpublished" | "suspended";
  draft_version: number; live_version: number; published_at: string | null; publish_state: "idle" | "publishing" | "failed"; publish_error: string | null; publish_attempted_at: string | null;
  commercial: { status: string; reason: string | null; billing_period: string | null; paid_until: string | null; grace_until: string | null; updated_at: string | null };
  business_active: boolean; created_at: string; updated_at: string; assets: SiteAssetInfo[];
  domains: { id: string; hostname: string; domain_type: string; status: string; is_primary: boolean }[];
  enquiries: { new: number; total: number };
  revisions: { revision: number; hosting_version: number; created_at: string; note: string | null }[];
  draft_content?: SiteContent; readiness?: Blocker[]; edits_this_month?: number;
}
export interface SiteConfig { enabled: boolean; base_domain: string; provider: string; grace_days: number; enquiry_retention_days: number; pricing: { monthly_inr: number; annual_inr: number; setup_inr: number; edits_included_per_month: number; note: string } }
export interface EnquiryInfo { id: string; name: string; phone: string | null; email: string | null; message: string; status: "new" | "contacted" | "resolved" | "spam"; received_at: string; consent_at: string }

export const STATUS_LABEL: Record<string, string> = { draft: "Draft", published: "Live", unpublished: "Offline", suspended: "Suspended" };
export const STATUS_TONE: Record<string, "gray" | "green" | "amber" | "red"> = { draft: "gray", published: "green", unpublished: "amber", suspended: "red" };
export const COMMERCIAL_LABEL: Record<string, string> = { complimentary: "Complimentary", paid_offline: "Paid (recorded offline)", expired: "Expired", suspended: "Suspended" };
export const COMMERCIAL_TONE: Record<string, "gray" | "green" | "amber" | "red"> = { complimentary: "gray", paid_offline: "green", expired: "amber", suspended: "red" };
export const CTA_LABEL: Record<string, string> = { call: "Call", whatsapp: "WhatsApp", enquiry: "Enquiry form", directions: "Directions", order: "Order or booking link" };
export const ONLY_ONCE = ["hero", "contact", "disclaimer", "hours", "location"];

/** A copy of `arr` with the item at `from` moved to `to` (clamped). */
export function moveItem<T>(arr: readonly T[], from: number, to: number): T[] {
  const out = arr.slice();
  if (from < 0 || from >= out.length) return out;
  const t = Math.max(0, Math.min(out.length - 1, to));
  const [x] = out.splice(from, 1);
  out.splice(t, 0, x);
  return out;
}

export function blankValue(spec: FieldSpec): unknown {
  switch (spec.kind) {
    case "bool": return false;
    case "asset": return null;
    case "list": case "strings": return [];
    case "select": return spec.options?.[0] ?? "";
    default: return "";
  }
}

export function blankItem(fields: FieldSpec[]): Record<string, unknown> {
  return Object.fromEntries(fields.map((f) => [f.key, blankValue(f)]));
}

/** A new section id that matches the server's rule (a letter then letters or digits, 2 to 12 characters) and is not already used. */
export function newSectionId(existing: readonly string[], rand: () => number = Math.random): string {
  for (let i = 0; i < 200; i++) {
    const id = "s" + Math.floor(rand() * 36 ** 4).toString(36).padStart(3, "0");
    if (!existing.includes(id)) return id;
  }
  return "s" + existing.length.toString(36) + "x";
}

/** Section types an administrator may still add: allowed by the template, and not a type that may appear only once when it is already there. */
export function addableSections(allowed: readonly string[], sections: readonly { type: string }[], cap = 20): string[] {
  if (sections.length >= cap) return [];
  return allowed.filter((t) => !(ONLY_ONCE.includes(t) && sections.some((s) => s.type === t)));
}

/** Server errors keyed by path: "sections[2].data.items[0].title" -> message. Also answers "is there an error under this prefix". */
export function errorMap(errors: readonly { path: string; message: string }[] | undefined): Record<string, string> {
  return Object.fromEntries((errors ?? []).map((e) => [e.path, e.message]));
}
export const hasErrorUnder = (map: Record<string, string>, prefix: string) => Object.keys(map).some((k) => k === prefix || k.startsWith(prefix + ".") || k.startsWith(prefix + "["));

/** Immutable set of a value at a dotted path with [n] indexes: setPath(c, "business.phone", "x"). */
export function setPath<T>(obj: T, path: string, value: unknown): T {
  const parts = path.match(/[^.[\]]+/g) ?? [];
  const walk = (node: unknown, i: number): unknown => {
    if (i === parts.length) return value;
    const key = parts[i];
    if (Array.isArray(node)) { const idx = Number(key); const c = node.slice(); c[idx] = walk(node[idx], i + 1); return c; }
    const o = { ...(node as Record<string, unknown>) };
    o[key] = walk(o[key], i + 1);
    return o;
  };
  return walk(obj, 0) as T;
}

export const charsLeft = (s: string | null | undefined, max: number) => max - (s ?? "").length;

/** Days until a date (negative = past), from a date or ISO string; null when there is none. */
export function daysUntil(d: string | null | undefined, now: Date = new Date()): number | null {
  if (!d) return null;
  const t = new Date(d).getTime();
  return Number.isNaN(t) ? null : Math.ceil((t - now.getTime()) / 86_400_000);
}

export const DEVICES = { desktop: { label: "Desktop", width: 1280, height: 800 }, mobile: { label: "Mobile", width: 390, height: 780 } } as const;
export type Device = keyof typeof DEVICES;
/** Scale that fits a device-width frame into `available` pixels (never enlarges). */
export const fitScale = (device: Device, available: number) => Math.min(1, Math.max(0.2, available / DEVICES[device].width));

/** What the next action on a site is, in words, for the status strip. */
export function nextStep(site: Pick<SiteInfo, "status" | "live_version" | "publish_state" | "commercial">, blockers: number, dirty: boolean): string {
  if (site.status === "suspended") return "This website is suspended. Resume it from Settings when the reason has been resolved.";
  if (site.publish_state === "failed") return "The last publish failed. The website that was live is unchanged. Fix the problem and publish again.";
  if (!["complimentary", "paid_offline"].includes(site.commercial.status)) return "Hosting is not active. Record it as complimentary or paid in Settings before publishing.";
  if (dirty) return "You have unsaved changes. Save the draft to update the preview.";
  if (blockers > 0) return `${blockers} thing${blockers === 1 ? "" : "s"} to fix before this can be published.`;
  return site.status === "published" ? "Live. Publish again to make your latest saved draft live." : "Ready to publish.";
}
