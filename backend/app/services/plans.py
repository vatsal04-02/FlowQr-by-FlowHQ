"""The commercial plan catalogue: one place that says what each plan is, what it includes and which AI calls draw on which allowance.

The database table `billing_plans` is what the application reads at run time (and what an admin can see and, for the unapproved limits, set). This module is the
specification that table is seeded from (migration 0029) and that a test compares it against, so the two cannot drift apart silently.

Prices and allowances below are the CONFIRMED commercial terms. Everything the owner has NOT approved is `None` here, which the application treats as "not configured": the
feature that needs it stays off (fails closed) until an admin sets a real value. Nothing in this file invents a number."""
from __future__ import annotations

# --------------------------------------------------------------------------------------------------------------------------------------------- features
# Every plan feature is a key in `subscriptions.features`; routes, workers and scheduled jobs check them through services/entitlements.
CORE = ("review_sync", "ai_replies", "review_generation", "qr_campaigns", "review_analytics", "gbp_connection", "gbp_info")
GROWTH_ADD = ("gbp_posts", "gbp_media", "gbp_performance", "insights", "local_seo", "keyword_tracking", "geo_ranking", "autonomy", "ai_posts", "profile_optimizer", "growth_agent")
PRO_ADD = ("multi_location",)
ALL_FEATURES = CORE + GROWTH_ADD + PRO_ADD

FEATURE_LABELS = {
    "review_sync": "Review sync", "ai_replies": "AI review replies", "review_generation": "Review writing assistant", "qr_campaigns": "QR and NFC campaigns",
    "review_analytics": "Review analytics", "gbp_connection": "Google Business Profile connection", "gbp_info": "Business profile editing", "gbp_posts": "Google Posts",
    "gbp_media": "Photos", "gbp_performance": "Search performance", "insights": "Insights", "local_seo": "Local SEO", "keyword_tracking": "Keyword tracking",
    "geo_ranking": "Geographic ranking maps", "autonomy": "Autonomous SEO maintenance", "ai_posts": "AI Google Posts", "profile_optimizer": "AI Profile Optimizer",
    "growth_agent": "AI Growth Agent", "multi_location": "Multi-location management",
}

# --------------------------------------------------------------------------------------------------------------------------------------------- allowances
# Two SEPARATE monthly allowances. A plan with 400 and 400 has 800 operations in total, not 400 shared.
REVIEW_GENERATION_KINDS = frozenset({"review_generate", "review_assist"})  # the customer-facing review-writing assistant
REPLY_KINDS = frozenset({"reply_draft"})  # AI replies to Google reviews, wherever they are drafted (inbox, tasks, the daily agent)
QUOTA_FIELDS = {"review_generation": "review_generations", "review_reply": "review_replies"}
# Every other AI task (Google Posts, descriptions, the growth agent's analysis, the safety read) has NO per-plan count in the confirmed terms. It is limited by its plan
# feature and by the USD budgets (services/ai_usage.py), never by pretending it is a review generation.

GEO_KEYS = ("max_grids", "max_points", "monthly_points")  # the geo-grid allowances the owner has not approved; None = not configured = maps stay off
UNAPPROVED_LIMITS = {
    "limits.geo.max_grids": "maps per location", "limits.geo.max_points": "points per map", "limits.geo.monthly_points": "map searches per month",
}

PLANS: dict[str, dict] = {
    "starter": {"name": "Starter", "price_paise": 49900, "max_locations": 1, "max_staff": 3, "review_generations": 200, "review_replies": 200, "features": list(CORE), "sort_order": 1},
    "growth": {"name": "Growth", "price_paise": 79900, "max_locations": 1, "max_staff": 10, "review_generations": 400, "review_replies": 400, "features": list(CORE + GROWTH_ADD), "sort_order": 2},
    "pro": {"name": "Pro", "price_paise": 149900, "max_locations": 10, "max_staff": 50, "review_generations": 800, "review_replies": 800, "features": list(ALL_FEATURES), "sort_order": 3},
}
# Retired codes: kept so existing subscribers and Razorpay plan ids keep resolving, never offered to anyone new.
LEGACY = {"essential": "starter", "multi": "pro"}
for _p in PLANS.values():
    _p["monthly_ai_generations"] = _p["review_generations"] + _p["review_replies"]  # display total only
    _p["limits"] = {"geo": {k: None for k in GEO_KEYS}}

# Assumptions the owner has not confirmed (surfaced in /admin/plans and the completion report):
#   * Growth includes ONE location ("No by default"); Pro's cap of 10 is carried over from the retired Multi plan.
#   * Starter keeps manual profile editing; Posts and Photos start at Growth.
#   * Staff seats are carried over from the retired plans (3 / 10 / 50).
ASSUMPTIONS = (
    "Growth includes one location (multi-location is 'No by default' in the commercial table).",
    "Pro allows 10 locations: carried over from the retired Multi plan, not stated in the commercial table.",
    "Starter keeps manual profile editing; Google Posts and Photos start at Growth.",
    "Staff seats (3 / 10 / 50) are carried over from the retired plans.",
)


def quota_field_for(kind: str | None) -> str | None:
    """Which allowance an AI task draws on: 'review_generations', 'review_replies', or None (no per-plan count)."""
    if kind in REVIEW_GENERATION_KINDS:
        return QUOTA_FIELDS["review_generation"]
    if kind in REPLY_KINDS:
        return QUOTA_FIELDS["review_reply"]
    return None


def kinds_for(field: str) -> frozenset:
    return {"review_generations": REVIEW_GENERATION_KINDS, "review_replies": REPLY_KINDS}[field]


def geo_limits(limits: dict | None) -> dict | None:
    """The usable geo-grid allowances, or None unless EVERY one is a positive whole number (a half-configured plan is an unconfigured plan)."""
    g = (limits or {}).get("geo") or {}
    vals = {k: g.get(k) for k in GEO_KEYS}
    if all(isinstance(v, int) and not isinstance(v, bool) and v > 0 for v in vals.values()):
        return vals
    return None


def pending_limits(limits: dict | None) -> list[str]:
    g = ((limits or {}).get("geo")) or {}
    return [f"limits.geo.{k}" for k in GEO_KEYS if not (isinstance(g.get(k), int) and not isinstance(g.get(k), bool) and g.get(k) > 0)]
