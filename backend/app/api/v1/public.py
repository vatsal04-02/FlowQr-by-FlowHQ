"""Unauthenticated endpoints used by the QR/NFC landing page. Hardened: rate limits, bot filtering,
no internal IDs in responses, and no tenant data beyond what the customer should see."""
import time
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import public_db
from app.core.rate_limit import client_ip, hit, limit_by_ip
from app.models import CardStatus, Location, QRCard, ScanEvent, ScanEventType, Tenant
from app.models.base import utcnow
from app.schemas.cards import TrackEventIn
from app.services import cards as svc
from app.services.ai import AIUnavailable, get_provider
from app.services.ai.review_assist import improve_review
from app.services.ai_usage import log_generation, quota_exceeded

router = APIRouter(prefix="/public/c", tags=["public"])

AI_DISCLAIMER = "AI-assisted suggestion based on what you wrote. Edit it so it's truly your own words before posting."


class AssistIn(BaseModel):
    text: str = Field(min_length=1, max_length=5000)
    language: str = Field(default="auto", pattern="^(auto|en|hi|hinglish)$")


def _find_card(db: Session, token: str) -> QRCard | None:
    if not (16 <= len(token) <= 64):
        return None
    return db.scalar(select(QRCard).where(QRCard.public_token == token))


def _fallback(state: str) -> dict:
    messages = {
        "unassigned": "This FlowQR card hasn't been set up yet.",
        "inactive": "This FlowQR card is no longer active.",
        "not_found": "We couldn't find this card.",
    }
    return {"state": state, "message": messages[state]}


@router.get("/{token}", dependencies=[Depends(limit_by_ip("scan", settings.rl_public_scan_per_minute, 60))])
def resolve_card(token: str, request: Request, db: Session = Depends(public_db)):
    """Resolve token -> card -> business/location, record a scan, return what the landing page needs."""
    ua = request.headers.get("user-agent")
    ip = client_ip(request)
    card = _find_card(db, token)
    if not card:
        # Not recorded: unknown tokens are probes and would otherwise grow the table unbounded.
        raise HTTPException(status_code=404, detail=_fallback("not_found"))

    if card.status == CardStatus.unassigned or not card.tenant_id:
        svc.record_event(db, card, ScanEventType.fallback, ip=ip, ua=ua)
        db.commit()
        return _fallback("unassigned")
    if card.status not in svc.LIVE_STATUSES:
        svc.record_event(db, card, ScanEventType.fallback, ip=ip, ua=ua)
        db.commit()
        return _fallback("inactive")

    tenant = db.get(Tenant, card.tenant_id)
    location = db.get(Location, card.location_id) if card.location_id else None
    if not tenant or not tenant.is_active or not location or not location.is_active:
        svc.record_event(db, card, ScanEventType.fallback, ip=ip, ua=ua)
        db.commit()
        return _fallback("inactive")

    vhash = svc.visitor_hash(ip, ua)
    recent = db.scalar(select(ScanEvent.id).where(
        ScanEvent.card_id == card.id, ScanEvent.event_type == ScanEventType.scan, ScanEvent.visitor_hash == vhash,
        ScanEvent.created_at > utcnow() - timedelta(seconds=20)).limit(1))
    if not recent:  # ignore rapid refreshes
        svc.record_event(db, card, ScanEventType.scan, ip=ip, ua=ua)
        if card.status == CardStatus.assigned and not svc.is_bot(ua):
            card.status = CardStatus.active  # first genuine scan makes the card live
        db.commit()

    return {
        "state": "ok",
        "business": {
            "name": tenant.name,
            "logo_url": tenant.logo_url,
            "category": tenant.category,
            "language": tenant.language,
        },
        "location": {
            "name": location.name,
            "city": location.city,
            "address": ", ".join(p for p in [location.address_line, location.city] if p) or None,
        },
        "review_url": location.review_url,
        "ai_available": settings.ai_configured,
        "ai_disclaimer": AI_DISCLAIMER,
        "card_code": card.card_code,
    }


@router.post("/{token}/event", status_code=204, dependencies=[Depends(limit_by_ip("event", 120, 60))])
def track_event(token: str, body: TrackEventIn, request: Request, db: Session = Depends(public_db)):
    card = _find_card(db, token)
    if not card or card.status not in svc.LIVE_STATUSES or not card.tenant_id:
        return
    svc.record_event(db, card, ScanEventType(body.type), ip=client_ip(request), ua=request.headers.get("user-agent"))
    db.commit()


@router.post("/{token}/assist")
def assist(token: str, body: AssistIn, request: Request, db: Session = Depends(public_db)):
    """Polish the customer's own words. Same rules for everyone: no sentiment gating, no star prompts."""
    ip = client_ip(request)
    if not hit(f"assist:{ip}:{token}", settings.rl_public_ai_per_10min, 600) or not hit(f"assist-ip:{ip}", 30, 3600):
        raise HTTPException(status_code=429, detail="You've reached the limit for now. You can still post your own words as written.")
    card = _find_card(db, token)
    if not card or card.status not in svc.LIVE_STATUSES or not card.tenant_id:
        raise HTTPException(status_code=404, detail="Card not available")
    text = body.text.strip()
    if len(text) < 8:
        raise HTTPException(status_code=422, detail="Please write a little more about your experience first.")
    if len(text) > settings.public_ai_max_input_chars:
        raise HTTPException(status_code=422, detail=f"Please keep it under {settings.public_ai_max_input_chars} characters.")
    tenant = db.get(Tenant, card.tenant_id)
    if quota_exceeded(db, tenant.id):
        raise HTTPException(status_code=503, detail="The writing assistant is unavailable right now. You can still post your own words.")

    started = time.monotonic()
    try:
        provider = get_provider()
    except AIUnavailable:
        raise HTTPException(status_code=503, detail="The writing assistant is unavailable right now. You can still post your own words.")
    try:
        suggestion, lang = improve_review(provider, text, language=body.language, business_name=tenant.name, category=tenant.category)
    except AIUnavailable as exc:
        log_generation(db, tenant_id=tenant.id, kind="review_assist", provider=provider.name, model=provider.model,
                       language=body.language, input_chars=len(text), output_chars=0, status="error",
                       started=started, location_id=card.location_id, card_id=card.id, error=str(exc))
        db.commit()
        raise HTTPException(status_code=503, detail="We couldn't improve your text just now. You can still post your own words.")
    log_generation(db, tenant_id=tenant.id, kind="review_assist", provider=provider.name, model=provider.model,
                   language=lang, input_chars=len(text), output_chars=len(suggestion), status="ok",
                   started=started, location_id=card.location_id, card_id=card.id)
    svc.record_event(db, card, ScanEventType.ai_assist, ip=ip, ua=request.headers.get("user-agent"))
    db.commit()
    return {"suggestion": suggestion, "language": lang, "ai_assisted": True, "disclaimer": AI_DISCLAIMER}
