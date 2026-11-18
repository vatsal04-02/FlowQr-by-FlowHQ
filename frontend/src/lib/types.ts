export type Role = "owner" | "admin" | "staff";

export interface Tenant {
  id: string; name: string; slug: string; category: string | null; email: string | null; phone: string | null;
  address: string | null; website: string | null; language: "en" | "hi" | "hinglish"; timezone: string;
  logo_url: string | null; brand_tone: string | null; ai_instructions: string | null; onboarding_completed: boolean;
  suspended_at: string | null; suspension_reason: string | null; support_status: string;
  /** reviews per calendar month the owner aims for; null = not set (the Overview suggests one) */
  review_goal?: number | null;
  /** asked in onboarding: has_site | wants_site (FlowQR may build one) | not_now; null = never asked */
  website_interest?: "has_site" | "wants_site" | "not_now" | null;
}
export interface User { id: string; email: string; full_name: string; phone: string | null; picture_url?: string | null; is_platform_admin: boolean; email_verified_at: string | null; has_local_login: boolean; google_linked: boolean }
export interface Me {
  user: User; memberships: { tenant: Tenant; role: Role }[]; active_tenant_id: string | null; csrf_token: string;
  integrations: { google_configured: boolean; ai_configured: boolean; public_card_base_url: string };
}
export interface Location {
  id: string; name: string; address_line: string | null; city: string | null; state: string | null; postal_code: string | null;
  phone: string | null; review_url: string | null; review_url_source: string; is_active: boolean;
}
export type CardStatus = "generated" | "unassigned" | "reserved" | "assigned" | "active" | "paused" | "archived" | "retired" | "deactivated" | "lost";
export interface Card {
  id: string; card_code: string; status: CardStatus; batch_id: string | null; tenant_id: string | null; location_id: string | null;
  label: string | null; assigned_at: string | null; url: string; public_token?: string | null; tenant_name: string | null;
  location_name: string | null; stats: Record<string, number>; last_scan_at?: string | null;
  /** what the printed QR encodes, and what is written on the NFC tag: both resolve to this one card */
  nfc_url?: string | null; campaign_id?: string | null; campaign_name?: string | null; batch_name?: string | null;
  /** where a scan goes INSTEAD of the review page (null = the review page), and an admin's statement that the NFC tag was written */
  destination_url?: string | null; nfc_programmed_at?: string | null;
}
export interface Batch { id: string; name: string; prefix: string; quantity: number; created_at: string; notes: string | null; released_at?: string | null }
export interface GoogleConnection { id: string; google_email: string | null; status: string; last_error: string | null; connected_at: string | null; api_access?: "unknown" | "approved" | "awaiting_approval" | "api_disabled"; api_access_checked_at?: string | null; locations_found?: number; no_locations?: boolean }
export interface GoogleLocation {
  id: string; connection_id: string; location_id: string | null; google_account_name: string; google_location_name: string;
  title: string | null; address: string | null; selected: boolean; last_synced_at: string | null; last_sync_status: string | null; last_sync_error: string | null;
}
export interface Draft {
  id: string; review_id: string; body: string; status: "draft" | "approved" | "publishing" | "published" | "failed" | "rejected"; language: string;
  generated_by_ai: boolean; requires_human_handling: boolean; flag_reasons: string[]; flag_messages: string[];
  approved_at: string | null; published_at: string | null; failure_reason: string | null; attempts: number; created_at: string;
}
export interface Review {
  id: string; location_id: string | null; location_name: string | null; rating: number; text: string | null; reviewer_name: string | null;
  review_created_at: string; review_updated_at: string | null; update_count: number; google_reply_text: string | null;
  google_reply_at: string | null; google_reply_state?: "PENDING" | "APPROVED" | "REJECTED" | null; reply_state: "none" | "draft" | "approved" | "publishing" | "published" | "failed"; sensitive_reasons: string[]; latest_draft: Draft | null;
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
    by_channel?: Record<"qr" | "nfc" | "untracked", { scans: number; unique_visitors: number; landing_views: number; google_clicks: number }>;
    series: SeriesPoint[]; definitions: Record<string, string>;
  };
  cards: { card_code: string; label: string | null; location: string | null; status: string; scans: number; landing_views: number; google_clicks: number; ai_assists: number }[];
  locations: { location: string; scans: number; landing_views: number; google_clicks: number; new_reviews: number; avg_rating: number | null }[];
  ai: { used_this_month: number; monthly_limit: number | null; in_range_by_kind: Record<string, number> };
  sync: { title: string | null; location: string | null; last_synced_at: string | null; status: string | null; error: string | null }[];
}

export interface Plan { code: string; name: string; price_paise: number; currency: string; interval: string; max_locations: number; monthly_ai_generations: number; review_generations: number; review_replies: number; max_staff: number; features: string[] }
export interface CardOffer { code: string; quantity: number; price_paise: number; includes: string }
/** The prepaid price list from /billing/plans (backend/app/services/plans.py is the only place the amounts are written). Keys of prices_paise are plan code, then months as a string. */
export interface PrepaidTerms { months: number[]; prices_paise: Record<string, Record<string, number>>; checkout_open: boolean }
export interface PlansResponse { plans: Plan[]; terms?: PrepaidTerms; trial_days: number; billing: { configured: boolean; mode: "test" | "live" | null; key_id: string | null; provider?: "cashfree" | "razorpay" | null; authorization_paise?: number; methods?: string[]; mandate_required?: boolean }; card_price_paise: number | null; card_ordering_enabled: boolean; card_offers: CardOffer[]; card_offer_note: string }
export interface SubscriptionInfo {
  billing: PlansResponse["billing"]; status: string; active: boolean; inactive_reason: string | null; plan: string | null; plan_name: string | null; price_paise: number | null;
  trial_ends_at: string | null; trial_days_left: number | null; current_period_end: string | null; cancel_at_period_end: boolean; pending_plan: string | null;
  grace_until: string | null; source: string | null; has_razorpay_subscription: boolean;
  provider?: string | null; has_cashfree_subscription?: boolean; authorization_status?: string | null; billing_state?: string; first_charge_at?: string | null; next_charge_at?: string | null;
  trial_entitlement?: string | null; trial_entitlement_name?: string | null; selected_plan?: string | null; selected_plan_name?: string | null; pending_plan_name?: string | null; pending_plan_effective_at?: string | null;
  mandate_required?: boolean; trial_started_at?: string | null; payment_method?: string | null; next_charge_amount_paise?: number | null;
  limits: { locations: number; ai_generations: number; review_generations: number; review_replies: number; staff: number; features: string[] };
  usage: { locations: number; ai_generations: number; review_generations: number; review_replies: number; staff: number };
  promo: { plan: string; plan_name: string; ends_at: string; kind: string; note: string } | null;
}
/** A temporary price that exists for THIS business only (usually none). Informational: the server decides the amount again when the order is created. */
export interface PrepaidOffer { plan: string; months: number; amount_paise: number; list_price_paise: number; label: string; expires_at: string }
/** The server's answer about a prepaid order. state: paid | pending | failed | expired | mismatch | open. */
export interface PrepaidResult { state: "paid" | "pending" | "failed" | "expired" | "mismatch" | "open"; order_id: string; plan: string; months: number; amount_paise: number; ends_at: string | null; failure_reason: string | null; unconfirmed?: boolean }
export interface SubscriptionEvent { at: string; kind: string; from_status: string | null; to_status: string | null; from_plan: string | null; to_plan: string | null; source: string; meta: Record<string, unknown> }
export interface Payment { id: string; provider?: string | null; payment_type?: string | null; failure_reason?: string | null; kind: "subscription" | "sub_auth" | "card_order"; status: string; amount_paise: number; currency: string; razorpay_payment_id: string | null; razorpay_order_id: string | null; razorpay_subscription_id: string | null; razorpay_invoice_id: string | null; method: string | null; error_description: string | null; paid_at: string | null; created_at: string }
export interface CardOrder { id: string; quantity: number; unit_price_paise: number; amount_paise: number; status: string; razorpay_order_id: string | null; tracking_note: string | null; created_at: string }
export interface Insights {
  total_reviews: number; reviews_with_text: number; sentiment: { positive: number; neutral: number; negative: number };
  topics: { topic: string; label: string; mentions: number; positive: number; neutral: number; negative: number; avg_rating: number; previous_mentions: number; sample: string | null }[];
  method: string; range: { from: string; to: string };
}

/** How a QR code is drawn. It never changes what the code encodes. Mirrors backend/app/schemas/qr.py. */
export interface QRStyle {
  dark: string; light: string; margin: number; error_correction: "L" | "M" | "Q" | "H"; size_px: number;
  use_logo: boolean; logo_scale: number; caption: string | null;
}
export interface QRStyleInfo { style: QRStyle; has_logo: boolean; is_default: boolean; verification: "decoded" | "rules_only" }
export const DEFAULT_QR_STYLE: QRStyle = { dark: "#111827", light: "#FFFFFF", margin: 4, error_correction: "H", size_px: 1024, use_logo: false, logo_scale: 0.2, caption: null };
export interface StaffMember { user_id: string; email: string; full_name: string; role: Role; all_locations: boolean; location_ids: string[] }
export interface StaffInvitation { id: string; email: string; role: Role; expires_at: string; location_ids?: string[] | null }
