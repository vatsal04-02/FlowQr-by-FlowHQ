"""The AI Growth Agent's autonomy matrix: for each of the six advertised capabilities, what it does by itself, what only a person can do,
how a result is verified, and what it will never do. It is served to the app (AI > Automations) and written into docs/AI_AUTONOMY.md.

Policy, enforced in code and covered by tests/test_autonomy.py:
  * The agent collects, analyses, recommends, drafts, schedules internal jobs, retries safe failures and reports ON ITS OWN.
  * Anything public (a Google Post, a photo, a profile change, an AI-drafted review reply) needs an owner/admin to approve it. There is no switch that
    turns this off: `auto_publish` is always false.
  * THE ONE EXCEPTION, an owner decision of 2026-11-15: a TEMPLATE reply to a new, clearly positive (4 and 5 star) review is sent without a person, with an off switch, a plan
    allowance and the safety rules in services/auto_reply.py. No AI writes it.
  * Nothing is reported as done until Google's own response says so.
"""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AgentTask, GbpSnapshot, ReplyDraft, ReplyStatus, ScheduledMedia, ScheduledPost
from app.models.base import utcnow

# The connected workflow every capability runs through (one shared agent, one business knowledge base).
STAGES = [
    ("collect", "Data collection", "agent"), ("analyze", "Analysis", "agent"), ("recommend", "Recommendation", "agent"), ("prepare", "AI preparation", "agent"),
    ("approve", "Approval", "owner"), ("publish", "Publishing", "system after approval"), ("verify", "Verification", "system"), ("report", "Activity report", "agent"),
]

CAPABILITIES = [
    {
        "id": "seo", "name": "SEO profile optimization",
        "independent": ["Read the live Business Profile (description, categories, services, hours; attributes are not read yet)", "Read Google's own search terms for the profile",
                        "Score the profile and list what is missing", "Draft a better description from your Business Brain (checked for claims you did not approve)",
                        "Apply a description improvement from your verified facts, ONLY if the owner switched autonomy on (Level 1); read it back from Google and record it"],
        "needs_approval": ["Level 2 profile changes (hours, contact details, services, secondary categories), unless you pre-authorised that exact type",
                           "Level 3 profile changes (name, primary category, address, attributes, service area, an existing primary phone or website, removing information, health claims): always, by the owner"],
        "verification": "After a profile change the agent re-reads the profile from Google and shows what Google now holds.",
        "never": ["Invent services, prices, awards or health claims", "Stuff keywords", "Change a Level 3 field, or anything without verified evidence, without the owner"],
        "sources": "Business Profile APIs (live) and Google's own search-term report. No third-party keyword database is used.",
    },
    {
        "id": "review_growth", "name": "Review growth",
        "independent": ["Watch review volume and rating trends", "Track QR and NFC card scans and campaign results", "Write neutral review-request wording (never asks for 5 stars)",
                        "Recommend where to place cards and which campaigns to run"],
        "needs_approval": ["Creating or changing a campaign or QR card destination (owner or admin)"],
        "verification": "Scans, review-page visits and Google review clicks are counted from real events; reviews appear only when Google returns them.",
        "never": ["Write or fake reviews", "Filter or hide negative feedback (everyone gets the same Google link)", "Offer rewards for ratings"],
        "sources": "FlowQR scan events and synced Google reviews.",
    },
    {
        "id": "replies", "name": "AI review replies",
        "independent": ["Sync new reviews from Google every 30 minutes", "Draft a personal reply from the rating, the review text and your Business Brain (if auto-drafting is on)",
                        "Flag risky reviews (health, legal, abuse) for a human", "Retry a reply that failed for a safe reason (rate limit, Google outage)"],
        "needs_approval": ["Every AI-drafted reply", "Every reply to a review of 3 stars or less, or one that is mixed, critical or sensitive"],
        "also_independent": ["Reply to NEW 4 and 5 star reviews from your own template (no AI), if automatic replies are on; they are on by default and you can switch them off"],
        "verification": "A reply counts as published only when Google returns it; if Google marks it rejected the review shows that and the owner is told.",
        "never": ["Answer a review that arrived before automatic replies were switched on", "Answer a sensitive, low or mixed review without a person", "Make promises, give medical advice or invent facts"],
        "sources": "Business Profile reviews API (live).",
    },
    {
        "id": "posts", "name": "Daily Google Posts",
        "independent": ["Pick a topic from your offers, season and Google's search terms", "Draft one post per location per day (if auto-drafting is on)",
                        "Check wording against your approved and prohibited claims", "Suggest a matching real photo (text only)", "Keep the publishing calendar",
                        "Retry a failed publish with back-off"],
        "needs_approval": ["Approving a post (this also schedules it)"],
        "verification": "A post is marked published only after Google returns its post ID; a failed one stays visible with the reason.",
        "never": ["Publish unapproved posts", "Invent offers, prices or dates"],
        "sources": "Your Business Brain and the Business Profile posts API (live).",
    },
    {
        "id": "photos", "name": "Photo management",
        "independent": ["Read existing profile photos and find missing categories and stale photos", "Recommend which genuine photos to add",
                        "Validate, store and organise the photos you upload", "Run scheduled uploads in the background", "Re-check Google until the photo is live"],
        "needs_approval": ["Every upload to Google (you choose the photo; approving schedules it)"],
        "verification": "Uploaded photos are re-read from Google; the app shows 'Google is processing it' until Google returns a live URL.",
        "never": ["Generate images of your premises, team or services", "Upload a photo you did not supply"],
        "sources": "Business Profile media API (live).",
    },
    {
        "id": "analytics", "name": "Performance analytics",
        "independent": ["Sync profile views, calls, website clicks, directions and search terms", "Spot trends and opportunities", "Build the dashboard and PDF/CSV reports",
                        "Recommend actions from the real numbers"],
        "needs_approval": ["Nothing: analytics is read-only"],
        "verification": "Every number comes from Google's Performance API; when Google returns no data the app says so instead of showing zero.",
        "never": ["Estimate or fill in missing numbers"],
        "sources": "Business Profile Performance API (live).",
    },
]


def matrix() -> dict:
    return {"stages": [{"id": i, "label": l, "actor": a} for i, l, a in STAGES], "capabilities": CAPABILITIES, "auto_publish": False, "auto_reply_templates": True,
            "rule": "Google Posts, photos and AI-drafted review replies always need a person's approval; a template reply to a new positive review is sent automatically (owner decision, with an off switch). Profile changes follow the Balanced Autonomy policy: Level 1 only runs on its own "
                    "when the owner turns autonomy on, Level 2 only for action types the owner pre-authorised, Level 3 always needs the owner.",
            "balanced_autonomy": {"policy_endpoint": "/agent/policy", "settings_endpoint": "/agent/autonomy-settings", "default": "on"}}


def pipeline_counts(db: Session, tenant_id: uuid.UUID, scope=None) -> dict:
    """Where the tenant's work is right now, per workflow stage, from real rows (RLS keeps this to the tenant)."""
    since = utcnow() - timedelta(days=30)

    def n(q) -> int:
        return db.scalar(q) or 0

    snaps = db.scalars(select(GbpSnapshot.fetched_at).where(GbpSnapshot.tenant_id == tenant_id, GbpSnapshot.error.is_(None), GbpSnapshot.fetched_at.is_not(None))).all()
    open_tasks = select(func.count()).select_from(AgentTask).where(AgentTask.tenant_id == tenant_id)
    drafts = n(select(func.count()).select_from(ReplyDraft).where(ReplyDraft.tenant_id == tenant_id, ReplyDraft.status == ReplyStatus.draft))
    awaiting_posts = n(select(func.count()).select_from(ScheduledPost).where(ScheduledPost.tenant_id == tenant_id, ScheduledPost.status == "awaiting_approval"))
    awaiting_media = n(select(func.count()).select_from(ScheduledMedia).where(ScheduledMedia.tenant_id == tenant_id, ScheduledMedia.status == "awaiting_approval"))
    profile_waiting = n(open_tasks.where(AgentTask.kind == "profile_fix", AgentTask.status == "awaiting_approval"))
    queued_posts = n(select(func.count()).select_from(ScheduledPost).where(ScheduledPost.tenant_id == tenant_id, ScheduledPost.status.in_(("approved", "scheduled", "publishing"))))
    queued_media = n(select(func.count()).select_from(ScheduledMedia).where(ScheduledMedia.tenant_id == tenant_id, ScheduledMedia.status.in_(("scheduled", "publishing"))))
    replies_pub = n(select(func.count()).select_from(ReplyDraft).where(ReplyDraft.tenant_id == tenant_id, ReplyDraft.status == ReplyStatus.published, ReplyDraft.published_at >= since))
    posts_pub = n(select(func.count()).select_from(ScheduledPost).where(ScheduledPost.tenant_id == tenant_id, ScheduledPost.status == "published", ScheduledPost.published_at >= since))
    media_pub = n(select(func.count()).select_from(ScheduledMedia).where(ScheduledMedia.tenant_id == tenant_id, ScheduledMedia.status == "published", ScheduledMedia.updated_at >= since))
    posts_ver = n(select(func.count()).select_from(ScheduledPost).where(ScheduledPost.tenant_id == tenant_id, ScheduledPost.status == "published", ScheduledPost.published_at >= since,
                                                                       ScheduledPost.google_post_name.is_not(None)))
    media_ver = n(select(func.count()).select_from(ScheduledMedia).where(ScheduledMedia.tenant_id == tenant_id, ScheduledMedia.status == "published", ScheduledMedia.updated_at >= since,
                                                                         ScheduledMedia.google_url.is_not(None)))
    failed = (n(select(func.count()).select_from(ReplyDraft).where(ReplyDraft.tenant_id == tenant_id, ReplyDraft.status == ReplyStatus.failed))
              + n(select(func.count()).select_from(ScheduledPost).where(ScheduledPost.tenant_id == tenant_id, ScheduledPost.status == "failed"))
              + n(select(func.count()).select_from(ScheduledMedia).where(ScheduledMedia.tenant_id == tenant_id, ScheduledMedia.status == "failed")))
    return {
        "collect": {"snapshots": len(snaps), "last_fetch": max(snaps).isoformat() if snaps else None},
        "recommend": {"open_suggestions": n(open_tasks.where(AgentTask.status == "suggested"))},
        "prepare": {"drafted": n(open_tasks.where(AgentTask.status == "drafted"))},
        "approve": {"waiting": drafts + awaiting_posts + awaiting_media + profile_waiting, "reply_drafts": drafts, "posts": awaiting_posts, "photos": awaiting_media, "profile": profile_waiting},
        "publish": {"queued": queued_posts + queued_media, "published_30d": replies_pub + posts_pub + media_pub, "replies": replies_pub, "posts": posts_pub, "photos": media_pub},
        "verify": {"confirmed_by_google_30d": replies_pub + posts_ver + media_ver, "published_30d": replies_pub + posts_pub + media_pub},
        "failed": failed,
    }
