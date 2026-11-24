import type { PostItem } from "./agent";

export type Objective = "keep_active" | "products" | "offers" | "enquiries" | "events" | "awareness";

export const OBJECTIVES: { value: Objective; label: string; hint: string }[] = [
  { value: "keep_active", label: "Keep my Google profile active", hint: "Steady, useful posts so your profile never looks abandoned." },
  { value: "products", label: "Promote products and services", hint: "Explain what you offer and who it is for." },
  { value: "offers", label: "Promote offers and discounts", hint: "Uses only real offers from your Business brain. Never invents a discount." },
  { value: "enquiries", label: "Generate local enquiries", hint: "Posts that make it easy to call, ask or book." },
  { value: "events", label: "Announce an event", hint: "You give the event name and dates; FlowQR writes the posts." },
  { value: "awareness", label: "Build local brand awareness", hint: "Who you are and the area you serve." },
];
export const DURATIONS = [{ value: 7, label: "7 days", posts: 3 }, { value: 15, label: "15 days", posts: 5 }, { value: 30, label: "30 days", posts: 8 }] as const;

/** The seven states an owner sees. FlowQR keeps "awaiting_approval" for a generated post nobody has approved yet. */
export const STUDIO_STATUS: Record<PostItem["status"], { label: string; tone: "idle" | "info" | "ok" | "warn" | "bad" }> = {
  draft: { label: "Draft", tone: "idle" }, awaiting_approval: { label: "Generated", tone: "warn" }, approved: { label: "Approved", tone: "info" }, scheduled: { label: "Scheduled", tone: "info" },
  publishing: { label: "Publishing", tone: "info" }, published: { label: "Published", tone: "ok" }, failed: { label: "Failed", tone: "bad" }, canceled: { label: "Canceled", tone: "idle" },
};

export interface Overview { campaigns: number; generated_posts: number; awaiting_review: number; approved: number; scheduled: number; published: number; failed: number; canceled: number }
export interface Readiness { can_publish: boolean; statement: string; approval_required: boolean; checks: { key: string; label: string; ok: boolean; detail: string; action: string | null }[] }
export interface Campaign {
  id: string; google_location_id: string; title: string; brief: string; objective: Objective; objective_label: string; duration_days: number; start_date: string; status: string;
  notes: string[]; keywords: string[]; created_at: string; counts: Record<string, number>; event_title: string | null; timezone?: string; posts?: StudioPost[];
}
export type StudioPost = PostItem & {
  campaign_id: string | null; asset_id: string | null; keywords: string[]; suggested_for: string | null;
  history?: { at: string; status: string; error: string | null; verified: boolean }[];
};
export interface Asset { id: string; kind: "image" | "document"; file_name: string | null; label: string | null; content_type: string; size_bytes: number; width: number | null; height: number | null; created_at: string; readable: boolean | null; in_use?: boolean; warnings?: string[] }
export interface SeoAssistant { city: string | null; keywords: string[]; missing: { field: string; question: string; why: string }[]; topics: string[]; avoid?: string; repetition: string | null; recent_post_types: string[]; note: string }

/** A time in the business's own zone as the value of a datetime-local input. */
export function toLocalInput(iso: string | null | undefined, tz: string): string {
  if (!iso || Number.isNaN(new Date(iso).getTime())) return "";
  try { return new Date(iso).toLocaleString("sv-SE", { timeZone: tz }).replace(" ", "T").slice(0, 16); } catch { return ""; }
}
export const fmtWhen = (iso: string | null | undefined, tz?: string) => (iso ? new Date(iso).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: tz }) : "");
