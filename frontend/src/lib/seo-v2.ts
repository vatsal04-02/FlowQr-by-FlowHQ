/** Shapes returned by GET /seo/v2/overview (backend/app/api/v1/seo_v2.py, services/agent/v2/overview.py). Every number here exists in the database or in Google's own answers: nothing is a placeholder. */
import type { ActionRow } from "./autonomy";

/** How a fix would be made, from the real policy, settings, consent and gate (not decided by the screen). */
export type FixMode = "automatic" | "owner_approved" | "recommended_only" | "owner_input_needed" | "unavailable_via_api" | "edit_in_google";
export type AreaState = "ok" | "improve" | "missing" | "unknown";

export interface V2Question { name: string; label: string; group: string | null; type: "BOOL" | "ENUM" | "REPEATED_ENUM" | "URL"; repeatable: boolean; choices: { value: unknown; label: string | null }[] }
export interface V2Area {
  key: string; label: string; state: AreaState; summary: string; fix: { mode: FixMode; label: string } | null; href?: string | null; note?: string | null;
  coverage?: { verified: number; on_google: number; missing: string[] }; questions?: V2Question[]; assessment?: Record<string, unknown>;
  recommendations?: { id: string; name: string; because: string; competitors_also_use: boolean }[];
}
export interface V2Diff { before: string[]; after: string[]; added: string[]; removed: string[]; changed: boolean }
export interface V2Action extends ActionRow { diff: V2Diff; v2: boolean; validation_status: string | null; executed_note: string | null }
export interface V2Opportunity { term: string; score: number; source: string; evidence: string[]; in_description: boolean }
export interface V2Location {
  google_location_id: string; title: string | null; profile_read: boolean; fetched_at: string | null; snapshot_error: string | null; note?: string;
  gate: { allowed: boolean; test_profile: boolean; customer_writes: boolean; reason: string | null };
  areas: V2Area[]; issues_detected?: number; google_changed?: string[]; opportunities: V2Opportunity[];
  actions: Record<"pending" | "recommended" | "in_progress" | "verified" | "failed" | "blocked" | "closed", V2Action[]>;
  completeness?: { known_areas: number; ok_areas: number; total_areas: number };
  performance: { current: number | null; previous: number | null; from: string; to: string; keywords: { keyword: string; value: number | null; below: number | null }[] } | null;
  rank_note?: string | null;
}
export interface V2Overview {
  generated_at: string; locations: V2Location[]; how_it_works: string; gate_note: string;
  totals: { issues_detected: number; optimizations_available: number; pending_approvals: number; recommended_only: number; in_progress: number; verified_on_google: number; verified_last_90_days: number; failed: number; blocked: number };
  health: { score: number | null; formula: string; components: { key: string; label: string; weight: number; available: boolean; value: number | null; detail: string }[] } | null;
}
