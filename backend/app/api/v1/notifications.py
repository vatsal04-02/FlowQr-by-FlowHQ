"""Bell, notification preferences and the command-palette search (PRD §6.5, §9). Read-only over existing data, tenant- and location-scoped."""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import or_, select

from app.core.deps import TenantContext, get_tenant_context
from app.models import Location, QRCard, Review
from app.models.base import utcnow
from app.services import notifications as svc

router = APIRouter(tags=["notifications"])


@router.get("/notifications")
def list_notifications(ctx: TenantContext = Depends(get_tenant_context)):
    prefs = svc.prefs_for(ctx.db, ctx.tenant_id, ctx.user.id)
    return svc.as_json(svc.collect(ctx.db, ctx.tenant, location_ids=ctx.location_ids), prefs.bell_seen_at)


@router.post("/notifications/seen")
def mark_seen(ctx: TenantContext = Depends(get_tenant_context)):
    prefs = svc.prefs_for(ctx.db, ctx.tenant_id, ctx.user.id, create=True)
    prefs.bell_seen_at = utcnow()
    ctx.db.commit()
    return {"seen_at": prefs.bell_seen_at}


class PrefsIn(BaseModel):
    email_new_review: bool
    email_flagged_review: bool
    email_sync_failed: bool
    email_trial_ending: bool


def _prefs_out(p) -> dict:
    return {k: getattr(p, k) for k in svc.DEFAULTS} | {"email": None}


@router.get("/notifications/preferences")
def get_prefs(ctx: TenantContext = Depends(get_tenant_context)):
    return _prefs_out(svc.prefs_for(ctx.db, ctx.tenant_id, ctx.user.id)) | {"email": ctx.user.email, "verified": ctx.user.email_verified_at is not None}


@router.put("/notifications/preferences")
def put_prefs(body: PrefsIn, ctx: TenantContext = Depends(get_tenant_context)):
    p = svc.prefs_for(ctx.db, ctx.tenant_id, ctx.user.id, create=True)
    for k, v in body.model_dump().items():
        setattr(p, k, v)
    if p.last_emailed_at is None:  # start the watermark now: switching emails on never mails the past
        p.last_emailed_at = utcnow()
    ctx.db.commit()
    return _prefs_out(p) | {"email": ctx.user.email, "verified": ctx.user.email_verified_at is not None}


@router.get("/search")
def search(q: str = Query(min_length=2, max_length=80), ctx: TenantContext = Depends(get_tenant_context)):
    """Command palette: reviews by reviewer or words, locations by name, cards by code or label. Five of each, newest reviews first."""
    like = "%" + q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"  # wildcards typed by a user are literal text
    reviews = ctx.db.scalars(select(Review).where(Review.tenant_id == ctx.tenant_id, ctx.scope(Review.location_id),
                                                  or_(Review.reviewer_name.ilike(like, escape="\\"), Review.text.ilike(like, escape="\\"))).order_by(Review.review_created_at.desc()).limit(5))
    locs = ctx.db.scalars(select(Location).where(Location.tenant_id == ctx.tenant_id, ctx.scope(Location.id), Location.name.ilike(like, escape="\\")).limit(5))
    cards = ctx.db.scalars(select(QRCard).where(QRCard.tenant_id == ctx.tenant_id, ctx.scope(QRCard.location_id),
                                                or_(QRCard.card_code.ilike(like, escape="\\"), QRCard.label.ilike(like, escape="\\"))).limit(5))
    return {
        "reviews": [{"id": str(r.id), "label": f"{r.reviewer_name or 'A Google user'} · {r.rating}★", "hint": (r.text or "Rating only")[:90], "href": f"/gbp/reviews/{r.id}"} for r in reviews],
        "locations": [{"id": str(l.id), "label": l.name, "hint": "Location", "href": "/gbp/locations"} for l in locs],
        "cards": [{"id": str(c.id), "label": c.card_code, "hint": c.label or "QR/NFC card", "href": f"/gbp/cards/{c.id}"} for c in cards],
    }
