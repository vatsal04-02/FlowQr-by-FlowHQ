// Shapes returned by /agent, /posts, /reports and /workspace. Mirrors backend/app/api/v1/{agent,posts,reports,workspace}.py.
export type TaskStatus = "suggested" | "drafted" | "awaiting_approval" | "approved" | "scheduled" | "published" | "failed" | "snoozed" | "dismissed" | "done";
export type TaskKind = "reply_review" | "create_post" | "profile_fix" | "add_photo" | "connect_google" | "complete_knowledge";
export interface Task {
  id: string; kind: TaskKind; title: string; why: string; evidence: Record<string, unknown> & { review_id?: string; field?: string; google_location_id?: string; state?: string };
  suggested_action: string | null; status: TaskStatus; draft: { description?: string } | null; ref_type: string | null; ref_id: string | null; priority: number; plan_date: string;
  snoozed_until: string | null; completed_at: string | null; failure_reason: string | null; created_at: string; location_id: string | null;
  reply?: { id: string; body: string; status: string; flags: string[]; review_id: string } | null; post?: { id: string; summary: string; status: string; scheduled_for: string | null } | null;
}
export interface TasksResponse { tasks: Task[]; counts: Record<string, number>; plan_date: string; last_plan_date: string | null }
export interface HealthComponent { key: string; label: string; weight: number; available: boolean; value: number | null; points: number | null; detail: string; improve: string }
export interface Health { score: number | null; covered_weight: number; components: HealthComponent[]; formula: string; message: string | null; changes: string[]; history: { day: string; score: number | null }[]; computed_at: string }
export interface Violation { code: string; message: string }
export interface Approvals {
  replies: { id: string; review_id: string; rating: number; reviewer: string | null; review_text: string; body: string; ai: boolean; flags: string[]; violations: Violation[]; created_at: string }[];
  posts: PostItem[]; profile: (Task & { violations: Violation[] })[];
}
export interface PostItem {
  id: string; google_location_id: string; location_title: string | null; summary: string; language: string; cta_type: string | null; cta_url: string | null; photo_url: string | null;
  status: "draft" | "awaiting_approval" | "approved" | "scheduled" | "publishing" | "published" | "failed" | "canceled"; scheduled_for: string | null; next_attempt_at: string | null;
  published_at: string | null; google_post_name: string | null; attempts: number; failure_reason: string | null; generated_by_ai: boolean; approved_at: string | null; created_at: string;
  violations: Violation[]; publish_result?: string | null;
  topic_type?: "STANDARD" | "OFFER" | "EVENT"; event_title?: string | null; event_start?: string | null; event_end?: string | null;
  offer_coupon?: string | null; offer_url?: string | null; offer_terms?: string | null; visual_hint?: string | null; topic_problems?: string[];
}
export interface Offer { name: string; price_inr: number | null; details: string | null; valid_until: string | null }
export interface Knowledge {
  business: string; category: string | null; description: string; services: string[]; offers: Offer[]; hours: string; faqs: { q: string; a: string }[]; brand_voice: string; audience: string;
  approved_claims: string[]; prohibited_claims: string[]; safety_profile: "general" | "health"; completeness: { missing: string[]; complete: boolean }; health_defaults: string[]; grounding_preview: string;
}
export interface Activity {
  runs: { id: string; kind: string; status: string; started_at: string; finished_at: string | null; detail: Record<string, unknown>; error: string | null }[];
  events: { task: string; from: string | null; to: string; actor: string; note: string | null; at: string }[];
  failed_posts: { id: string; summary: string; reason: string | null; attempts: number }[];
  queued_posts: { id: string; summary: string; scheduled_for: string | null; next_attempt_at: string | null; attempts: number; last_error: string | null }[];
  last_plan_run: { status: string; at: string; error: string | null } | null; last_plan_date: string | null; pending_approvals: number;
  ai: { used_this_month: number; monthly_limit: number; month_started: string };
}
export interface Integration { id: string; label: string; href: string | null; status: "connected" | "attention" | "not_connected" | "setup_required" | "not_available"; detail: string; steps: string[] }
export interface ReportSummary {
  range: { from: string; to: string; timezone: string };
  /** the selected location name, or null for all locations */
  location?: string | null;
  reputation: { reviews: number; average_rating: number | null; replied: number; reply_rate: number | null; avg_response_hours: number | null; unanswered_now: number; distribution: Record<string, number> };
  google_performance: { available: boolean; note: string; locations: { location: string; last_28_days: number; previous_28_days: number; fetched_at: string; window: string }[]; errors: { location: string; error: string }[] };
  campaigns: { scans: number; unique_visitors: number; feedback_submitted: number; drafts_approved: number; google_redirects: number } | null;
  ai_activity?: { ai_uses: { kind: string; status: string; count: number }[]; tasks_by_status: Record<string, number>; posts_by_status: Record<string, number>; replies_published: number };
}

export const TASK_LABEL: Record<TaskStatus, { label: string; tone: "idle" | "info" | "ok" | "warn" | "bad" }> = {
  suggested: { label: "Suggested", tone: "info" }, drafted: { label: "Drafted", tone: "info" }, awaiting_approval: { label: "Awaiting your approval", tone: "warn" },
  approved: { label: "Approved", tone: "info" }, scheduled: { label: "Scheduled", tone: "info" }, published: { label: "Published", tone: "ok" }, failed: { label: "Failed", tone: "bad" },
  snoozed: { label: "Snoozed", tone: "idle" }, dismissed: { label: "Dismissed", tone: "idle" }, done: { label: "Done", tone: "ok" },
};
export const POST_LABEL: Record<PostItem["status"], { label: string; tone: "idle" | "info" | "ok" | "warn" | "bad" }> = {
  draft: { label: "Draft", tone: "idle" }, awaiting_approval: { label: "Awaiting approval", tone: "warn" }, approved: { label: "Approved", tone: "info" }, scheduled: { label: "Scheduled", tone: "info" },
  publishing: { label: "Publishing", tone: "info" }, published: { label: "Published on Google", tone: "ok" }, failed: { label: "Failed", tone: "bad" }, canceled: { label: "Canceled", tone: "idle" },
};
