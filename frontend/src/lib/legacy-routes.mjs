// PRD §8 route migration: every URL the app used before the current layout, and where it lives now. Two generations are covered: the pre-redesign URLs (/dashboard, /cards ...)
// and the four-section URLs (/overview/performance, /gbp/rank, /ai/voice ...) that moved when the app became six sections (Phase 2: Workspace, Reputation, Local SEO, Analytics, AI Growth, Settings).
// next.config.mjs serves these as permanent (308) redirects that keep the query string, so emails, bookmarks, printed links,
// invitation links and the Google return URL of older deployments keep working. Keep for at least 90 days (PRD §8).
// Order matters: the more specific path comes first.
/** @type {[string, string][]} */
export const LEGACY_ROUTES = [
  // The book-a-demo page was removed: old links go to Sign up.
  ["/demo", "/register"],
  // ---- Phase 3 UI plan: GBP (was SEO & Google) and Growth sections (one hop from every older URL)
  ["/analytics/performance", "/seo/performance"],
  ["/analytics/reviews", "/reputation/insights"],
  ["/analytics/funnel", "/growth/funnel"],
  ["/analytics/campaigns", "/gbp/campaigns"],
  ["/analytics/reports", "/growth/reports"],
  ["/seo/rank", "/seo/rankings"],
  // ---- Phase 2: the four-section URLs that moved
  ["/overview/performance", "/seo/performance"],
  ["/overview/reviews", "/reputation/insights"],            // merged into Performance as its "Reviews" tab
  ["/overview/funnel", "/growth/funnel"],
  ["/overview/campaigns", "/gbp/campaigns"],
  ["/overview/reports", "/growth/reports"],
  ["/gbp", "/overview"],                                   // the GBP hub is merged into Overview and Local SEO
  ["/gbp/rank", "/seo/rankings"],
  ["/ai", "/reputation/drafts"],                           // the reply assistant is a tab of Reviews & Inbox
  ["/ai/insights", "/reputation/insights"],
  ["/ai/assistant/settings", "/reputation/assistant/settings"],
  ["/ai/assistant", "/reputation/assistant"],
  ["/ai/voice", "/settings/ai/voice"],
  ["/ai/brain", "/settings/ai/brain"],
  ["/ai/autonomy", "/settings/ai/autonomy"],
  ["/ai/usage", "/settings/ai/usage"],
  ["/settings/ai", "/settings/ai/usage"],                  // before the move this URL was the usage page
  // ---- Earlier generation: the pre-redesign URLs, pointed straight at today's pages
  ["/dashboard", "/overview"],
  ["/analytics", "/reputation/insights"],
  ["/cards/analytics", "/growth/funnel"],
  ["/performance", "/seo/performance"],
  ["/local-visibility", "/seo/rankings"],
  ["/overview/visibility", "/seo/rankings"],
  ["/reports", "/growth/reports"],
  ["/review-growth/analytics", "/gbp/campaigns"],
  ["/review-growth/campaigns/:id", "/gbp/campaigns/:id"],
  ["/review-growth/campaigns", "/gbp/campaigns"],
  ["/review-growth/customize", "/gbp/campaigns/landing"],
  ["/review-growth/generator", "/reputation/assistant"],
  ["/review-growth/settings", "/reputation/assistant/settings"],
  ["/review-growth", "/gbp/campaigns/guide"],
  ["/reviews/:id", "/gbp/reviews/:id"],
  ["/reviews", "/gbp/reviews"],
  ["/profile", "/gbp/info"],
  ["/posts", "/gbp/posts"],
  ["/media", "/gbp/photos"],
  ["/locations", "/gbp/locations"],
  ["/google", "/gbp/locations"],
  ["/cards/:id", "/gbp/cards/:id"],
  ["/cards", "/gbp/cards"],
  ["/qr", "/gbp/cards/designs"],
  ["/inbox/:path*", "/gbp/inbox/:path*"],
  ["/agent/recommendations", "/ai/tasks"],
  ["/agent/approvals", "/ai/approvals"],
  ["/agent/activity", "/ai/activity"],
  ["/agent/knowledge", "/settings/ai/brain"],
  ["/agent/automations", "/ai/automations"],
  ["/agent", "/ai/today"],
  ["/studio/:path*", "/ai/studio/:path*"],
  ["/staff", "/settings/team"],
  ["/subscription", "/settings/billing"],
  ["/payments", "/settings/billing/payments"],
];
