/** Shapes returned by /seo/* and /analytics/google-metrics (backend/app/api/v1/seo.py, analytics.py). */
export type Source = "places" | "google" | "flowqr";

export interface SeoKeyword { id: string; keyword: string; location: string | null; status: "ok" | "error" | null; rank: number | null; previous_rank: number | null; change: number | null; checked_at: string | null; error: string | null }
export interface SeoSummary { tracked: number; measured: number; never_measured: number; failed: number; top3: number; top10: number; top20: number; not_found: number; last_checked_at: string | null; source: Source; note: string }
export interface SeoTrendPoint { date: string; measured: number; top3: number; top10: number }
export interface GoogleTerm { keyword: string; value: number | null; small: boolean; tracked: boolean }
export interface SeoAttention { kind: string; keyword: string; detail: string; source: Source }
export interface SeoOverview {
  state: "ok" | "no_location" | "no_keywords"; sources: Record<Source, string>; provider_configured: boolean; tracking_allowed: boolean;
  locations: { id: string; title: string | null }[]; keywords: SeoKeyword[]; summary: SeoSummary | null; trend: SeoTrendPoint[];
  google_terms: { terms: GoogleTerm[]; months: string[]; fetched_at: string | null; source: Source; note: string } | null; attention: SeoAttention[];
}

export interface CompetitorKeyword { keyword: string; seen: number; best_position: number; ahead_of_you: number; your_checks: number }
export interface CompetitorChange { reviews_change: number; rating_change: number | null; from: string; to: string }
export interface PinnedSnapshot { at: string; date: string; rating: number | null; reviews: number | null; position: number | null }
export interface PinnedCompetitor {
  id: string; google_location_id: string; place_id: string; name: string; pinned_at: string; observations: number; first_observed_at: string | null; observed_at: string | null;
  rating: number | null; reviews: number | null; change: CompetitorChange | null; series: PinnedSnapshot[];
  visibility: { appeared_in: number; of_checks: number; in_top10: number; ahead_of_you: number; note: string };
}
export interface Competitor { place_id: string | null; name: string | null; google_location_ids?: string[]; pinned?: boolean; rating: number | null; reviews: number | null; observed_at: string; first_observed_at: string; observations: number; change: CompetitorChange | null; keywords: CompetitorKeyword[] }
export interface Competitors {
  pinned?: PinnedCompetitor[]; pin_limit?: number;
  stage: number; state: "ok" | "no_location" | "no_keywords" | "no_observations"; source: Source; provider_configured: boolean; competitors: Competitor[];
  you: { rating: number | null; reviews: number | null; observed_at: string; change: CompetitorChange | null } | null; observations: number; window_days: number; note: string;
  opportunities?: { kind: string; detail: string }[];
}

export interface HealthCheck { key: string; label: string; status: "ok" | "warn" | "missing"; detail: string; link: string | null; weight: number | null }
export interface HealthLocation { id: string; title: string | null; state: "ok" | "unavailable"; reason?: string; fetched_at: string | null; error: string | null; completeness: number | null; checks: HealthCheck[] }
export interface HealthComponent { key: string; label: string; weight: number; available: boolean; value: number | null; detail: string; improve: string; no_data: string }
export interface ProfileHealth {
  state: "ok" | "no_location"; locations: HealthLocation[];
  health: { score: number | null; covered_weight: number; components: HealthComponent[]; formula: string; message: string | null } | null;
}

export type GoogleMetricSummary = { search_views: number | null; maps_views: number | null; calls: number | null; website: number | null; directions: number | null; bookings: number | null; messages: number | null };
export interface GoogleMetrics {
  availability: { state: string; reason: string | null; last_fetched_at: string | null; locations_with_data: number };
  source: Source; range: { from: string; to: string }; current: GoogleMetricSummary | null; previous: GoogleMetricSummary | null;
  series: Record<string, { date: string; value: number }[]>; by_location: { id: string; title: string | null; days_with_data: number; totals: GoogleMetricSummary | null }[];
  days_with_data: number; range_days?: number; previous_range?: { from: string; to: string; days_with_data: number }; note: string;
}
