export type Role = "owner" | "admin" | "staff";

export interface Tenant {
  id: string; name: string; slug: string; category: string | null; email: string | null; phone: string | null;
  address: string | null; website: string | null; language: "en" | "hi" | "hinglish"; timezone: string;
  logo_url: string | null; brand_tone: string | null; ai_instructions: string | null; onboarding_completed: boolean;
}
export interface User { id: string; email: string; full_name: string; phone: string | null; is_platform_admin: boolean }
export interface Me {
  user: User; memberships: { tenant: Tenant; role: Role }[]; active_tenant_id: string | null; csrf_token: string;
  integrations: { google_configured: boolean; ai_configured: boolean; public_card_base_url: string };
}
export interface Location {
  id: string; name: string; address_line: string | null; city: string | null; state: string | null; postal_code: string | null;
  phone: string | null; review_url: string | null; review_url_source: string; is_active: boolean;
}
export type CardStatus = "unassigned" | "assigned" | "active" | "deactivated" | "lost";
export interface Card {
  id: string; card_code: string; status: CardStatus; batch_id: string | null; tenant_id: string | null; location_id: string | null;
  label: string | null; assigned_at: string | null; url: string; public_token?: string | null; tenant_name: string | null;
  location_name: string | null; stats: Record<string, number>;
}
export interface Batch { id: string; name: string; prefix: string; quantity: number; created_at: string; notes: string | null }
export interface GoogleConnection { id: string; google_email: string | null; status: string; last_error: string | null; connected_at: string | null }
export interface GoogleLocation {
  id: string; connection_id: string; location_id: string | null; google_account_name: string; google_location_name: string;
  title: string | null; address: string | null; selected: boolean; last_synced_at: string | null; last_sync_status: string | null; last_sync_error: string | null;
}
export interface Draft {
  id: string; review_id: string; body: string; status: "draft" | "approved" | "published" | "failed" | "rejected"; language: string;
  generated_by_ai: boolean; requires_human_handling: boolean; flag_reasons: string[]; flag_messages: string[];
  approved_at: string | null; published_at: string | null; failure_reason: string | null; attempts: number; created_at: string;
}
export interface Review {
  id: string; location_id: string | null; location_name: string | null; rating: number; text: string | null; reviewer_name: string | null;
  review_created_at: string; review_updated_at: string | null; update_count: number; google_reply_text: string | null;
  google_reply_at: string | null; reply_state: "none" | "draft" | "approved" | "published" | "failed"; sensitive_reasons: string[]; latest_draft: Draft | null;
}
export interface ReviewLog { id: string; draft_id: string | null; action: string; success: boolean; http_status: number | null; error: string | null; created_at: string }
export interface SeriesPoint { date: string; [k: string]: number | string }
export interface Overview {
  range: { from: string; to: string; timezone: string };
  reviews: {
    total_synced: number; average_rating_all_time: number | null; new_in_range: number; average_rating_in_range: number | null;
    awaiting_reply: number; drafts_pending_approval: number; reply_rate_in_range: number | null; avg_response_hours: number | null;
    rating_distribution: Record<string, number>; series: SeriesPoint[];
  };
  engagement: {
    scans: number; landing_views: number; google_clicks: number; ai_assists: number; click_through_rate: number | null;
    series: SeriesPoint[]; definitions: Record<string, string>;
  };
  cards: { card_code: string; label: string | null; location: string | null; status: string; scans: number; landing_views: number; google_clicks: number; ai_assists: number }[];
  locations: { location: string; scans: number; landing_views: number; google_clicks: number; new_reviews: number; avg_rating: number | null }[];
  ai: { used_this_month: number; monthly_limit: number | null; in_range_by_kind: Record<string, number> };
  sync: { title: string | null; location: string | null; last_synced_at: string | null; status: string | null; error: string | null }[];
}
