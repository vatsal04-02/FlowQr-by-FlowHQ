"""The one bundle of business facts the operator reasons from. Read-only and assembled from what the platform already holds (Business Brain, the business record, the Google profile snapshot,
reviews, posts, past decisions). Every part is labelled `verified` (the owner entered it, or Google returned it) or listed under `unknown` so the model is never invited to fill a gap by guessing."""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AgentAction, GbpSnapshot, GoogleLocation, ReplyDraft, Review, ScheduledPost, Tenant
from app.models.base import utcnow
from app.services.agent import knowledge as kbs

MAX_TEXT = 400


def _clip(s, n: int = MAX_TEXT):
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def business_context(db: Session, tenant: Tenant, gloc: GoogleLocation | None, ctx=None) -> dict:
    now = utcnow()
    kb = kbs.context(db, tenant)
    verified: dict = {
        "business_name": tenant.name, "category": tenant.category, "address": tenant.address, "phone": tenant.phone, "website": tenant.website, "language": tenant.language,
        "description_in_business_brain": _clip(kb.get("description")), "services": [s if isinstance(s, str) else s.get("name") for s in (kb.get("services") or [])][:30],
        "offers": [_clip(o if isinstance(o, str) else str(o), 160) for o in (kb.get("offers") or [])][:10], "faqs": len(kb.get("faqs") or []),
        "prohibited_claims": [_clip(c if isinstance(c, str) else str(c), 120) for c in (kb.get("prohibited_claims") or [])][:20], "hours_in_business_brain": kb.get("hours"),
    }
    unknown = [k for k in ("description", "services", "hours") if not kb.get(k)]
    google: dict | None = None
    if gloc is not None:
        snap = db.scalar(select(GbpSnapshot).where(GbpSnapshot.google_location_id == gloc.id))
        info = (snap.info or {}) if snap else {}
        google = {"google_location_id": str(gloc.id), "title": gloc.title, "profile_read": bool(info), "fetched_at": snap.fetched_at.isoformat() if snap and snap.fetched_at else None,
                  "description": _clip(info.get("description"), 750), "primary_category": (info.get("primary_category") or {}).get("name"),
                  "additional_categories": [c.get("name") for c in (info.get("additional_categories") or [])][:9], "website": info.get("website"), "phone": info.get("phone"),
                  "has_regular_hours": bool(info.get("hours")), "services_on_google": [(s.get("name") if isinstance(s, dict) else s) for s in (info.get("services") or [])][:30]}
        if not info:
            unknown.append("the Google profile has not been read yet")
    rq = select(Review).where(Review.tenant_id == tenant.id)
    if gloc is not None:
        rq = rq.where(Review.google_location_id == gloc.id)
    if ctx is not None:
        rq = rq.where(ctx.scope(Review.location_id))
    reviews = list(db.scalars(rq.order_by(Review.review_created_at.desc()).limit(200)))
    unanswered = [r for r in reviews if r.google_reply_text is None]
    review_ctx = {"recent_count": len(reviews), "average_rating": round(sum(r.rating for r in reviews) / len(reviews), 2) if reviews else None, "unanswered": len(unanswered),
                  "latest_unanswered": [{"id": str(r.id), "rating": r.rating, "text": _clip(r.text, 240), "date": r.review_created_at.date().isoformat()} for r in unanswered[:5]]}
    pq = select(ScheduledPost).where(ScheduledPost.tenant_id == tenant.id)
    if gloc is not None:
        pq = pq.where(ScheduledPost.google_location_id == gloc.id)
    posts = [{"status": p.status, "summary": _clip(p.summary, 160), "created": p.created_at.date().isoformat()} for p in db.scalars(pq.order_by(ScheduledPost.created_at.desc()).limit(5))]
    aq = select(AgentAction.status, AgentAction.field_key, AgentAction.updated_at).where(AgentAction.tenant_id == tenant.id, AgentAction.updated_at >= now - timedelta(days=60))
    if gloc is not None:
        aq = aq.where(AgentAction.google_location_id == gloc.id)
    decisions = [{"field": f, "status": s, "date": u.date().isoformat()} for s, f, u in db.execute(aq.order_by(AgentAction.updated_at.desc()).limit(15)).all()]
    waiting = db.scalar(select(func.count()).select_from(AgentAction).where(AgentAction.tenant_id == tenant.id, AgentAction.status.in_(("pending_approval", "recommended")))) or 0
    waiting += db.scalar(select(func.count()).select_from(ReplyDraft).where(ReplyDraft.tenant_id == tenant.id, ReplyDraft.status == "draft")) or 0
    return {"verified_facts": verified, "google_profile": google, "reviews": review_ctx, "recent_posts": posts, "recent_decisions": decisions, "waiting_for_owner": waiting,
            "unknown": unknown, "rule": "Only `verified_facts` and `google_profile` are facts. Anything in `unknown` must be asked, never assumed or invented."}
