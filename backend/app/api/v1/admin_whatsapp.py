"""WhatsApp add-on administration (platform administrators only). The add-on is recorded by hand: no billing, no plan change, no Cashfree. Works while WHATSAPP_ENABLED is false so a tier can be
recorded before launch."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.deps import AuthContext, require_platform_admin
from app.core.rate_limit import client_ip
from app.models import Tenant
from datetime import date
from decimal import Decimal

from app.services.whatsapp import WaError, addons, agent, ai_knowledge, attribution, connection, consent, occasions, pricing, rules

router = APIRouter(prefix="/admin", tags=["admin-whatsapp"])


class AddonIn(BaseModel):
    addon_key: str | None = Field(default=None, max_length=24)
    reason: str = Field(min_length=5, max_length=300)


def _tenant(ctx: AuthContext, tenant_id: uuid.UUID) -> Tenant:
    t = ctx.db.get(Tenant, tenant_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return t


@router.get("/tenants/{tenant_id}/whatsapp")
def summary(tenant_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    t = _tenant(ctx, tenant_id)
    return {"enabled": settings.whatsapp_enabled, "addon": addons.tier(addons.active_addon(ctx.db, t.id)), "tiers": [{"key": k, **v} for k, v in rules.ADDON_TIERS.items()],
            "connection": connection.serialize(connection.live_connection(ctx.db, t.id)), "counts": consent.counts(ctx.db, t.id)}


@router.put("/tenants/{tenant_id}/whatsapp-addon")
def set_addon(tenant_id: uuid.UUID, body: AddonIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    t = _tenant(ctx, tenant_id)
    try:
        addons.set_addon(ctx.db, ctx.user, t, body.addon_key, body.reason, client_ip(request))
        ctx.db.commit()
    except WaError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.detail())
    return {"addon": addons.tier(addons.active_addon(ctx.db, t.id))}


class RateIn(BaseModel):
    category: str = Field(max_length=16)
    rate: Decimal = Field(ge=0, le=1000)
    effective_from: date
    source: str = Field(min_length=10, max_length=300)
    verified: bool = False
    free_per_number_month: int = Field(default=0, ge=0, le=10_000_000)


class VerifyIn(BaseModel):
    verified: bool
    note: str = Field(min_length=10, max_length=300)


class FestivalIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    festival_date: date
    region: str = Field(default="All India", max_length=40)


class FestivalActiveIn(BaseModel):
    active: bool


@router.get("/whatsapp/festivals")
def festivals(ctx: AuthContext = Depends(require_platform_admin)):
    return {"items": occasions.list_festivals(ctx.db), "note": "Greetings for a festival go only to businesses that chose it, and only to customers who agreed to occasion greetings. A festival is never deleted, only switched off."}


@router.post("/whatsapp/festivals", status_code=201)
def festival_add(body: FestivalIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    try:
        f = occasions.add_festival(ctx.db, ctx.user, name=body.name, festival_date=body.festival_date, region=body.region, ip=client_ip(request))
        ctx.db.commit()
    except WaError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.detail())
    return occasions.serialize_festival(f)


@router.patch("/whatsapp/festivals/{festival_id}")
def festival_active(festival_id: uuid.UUID, body: FestivalActiveIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    try:
        f = occasions.set_festival_active(ctx.db, ctx.user, festival_id, body.active, ip=client_ip(request))
        ctx.db.commit()
    except WaError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.detail())
    return occasions.serialize_festival(f)


@router.get("/whatsapp/rates")
def rates(ctx: AuthContext = Depends(require_platform_admin)):
    return {"items": pricing.list_rates(ctx.db), "note": pricing.NOTE, "unverified_in_use": pricing.unverified_in_use(ctx.db, ("marketing", "utility", "authentication", "service"))}


@router.post("/whatsapp/rates", status_code=201)
def add_rate(body: RateIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Add a dated Meta rate (rates are never edited: a change is a new row with a new effective date)."""
    try:
        row = pricing.add_rate(ctx.db, ctx.user, category=body.category, rate=body.rate, effective_from=body.effective_from, source=body.source, verified=body.verified, free_per_number_month=body.free_per_number_month, ip=client_ip(request))
        ctx.db.commit()
    except WaError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.detail())
    return pricing.serialize(row, pricing.latest_verification(ctx.db, row.id))


@router.post("/whatsapp/rates/{rate_id}/verification", status_code=201)
def verify_rate(rate_id: uuid.UUID, body: VerifyIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Record a check of one rate against Meta's own rate card. This adds a record; the rate itself is never changed."""
    try:
        v = pricing.add_verification(ctx.db, ctx.user, rate_id, body.verified, body.note, ip=client_ip(request))
        ctx.db.commit()
    except WaError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.detail())
    return {"rate_id": rate_id, "verified": v.verified, "note": v.note, "at": v.created_at}


# ---- the assistant: monthly replies by tier (dated, append-only) and what it costs in real use
class AiQuotaIn(BaseModel):
    addon_key: str = Field(max_length=24)
    monthly_replies: int = Field(ge=0, le=100000)
    effective_from: date
    note: str = Field(min_length=5, max_length=300)


@router.get("/whatsapp/ai-quotas")
def ai_quotas(ctx: AuthContext = Depends(require_platform_admin)):
    from sqlalchemy import func, select
    from app.models.whatsapp import WhatsAppAiRun
    start = ai_knowledge.month_start()
    rows = ctx.db.execute(select(WhatsAppAiRun.provider, WhatsAppAiRun.model_version, func.count(), func.coalesce(func.sum(WhatsAppAiRun.prompt_tokens), 0), func.coalesce(func.sum(WhatsAppAiRun.completion_tokens), 0),
                                 func.coalesce(func.avg(WhatsAppAiRun.latency_ms), 0)).where(WhatsAppAiRun.is_test.is_(False), WhatsAppAiRun.created_at >= start).group_by(WhatsAppAiRun.provider, WhatsAppAiRun.model_version)).all()
    return {"items": ai_knowledge.list_quotas(ctx.db), "platform": {**{"on": agent.platform_availability().ok, "reason": agent.platform_availability().reason}, "terms_verified": agent.terms_ok(),
                                                                       "terms_provider": settings.whatsapp_ai_terms_provider or None, "provider": agent.provider_label()},
            "this_month": [{"provider": p, "model_version": m, "runs": c, "prompt_tokens": int(pt), "completion_tokens": int(ct), "avg_latency_ms": int(a)} for p, m, c, pt, ct, a in rows],
            "note": "Starting values are deliberately low for the limited beta. Change one by adding a row with a later date; set it from the tokens and latency recorded here."}


@router.post("/whatsapp/ai-quotas", status_code=201)
def add_ai_quota(body: AiQuotaIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    try:
        row = ai_knowledge.add_quota(ctx.db, ctx.user, addon_key=body.addon_key, monthly_replies=body.monthly_replies, effective_from=body.effective_from, note=body.note, ip=client_ip(request))
        ctx.db.commit()
    except WaError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.detail())
    return {"id": row.id, "addon_key": row.addon_key, "monthly_replies": row.monthly_replies, "effective_from": row.effective_from, "note": row.note}


# ---- the free entry-point window after an ad or page-button click (dated, append-only, unverified until checked)
class EntryWindowIn(BaseModel):
    hours: int = Field(ge=1, le=720)
    effective_from: date
    source: str = Field(min_length=10, max_length=300)


@router.get("/whatsapp/entry-windows")
def entry_windows(ctx: AuthContext = Depends(require_platform_admin)):
    return {"items": attribution.list_windows(ctx.db), "warning": attribution.WARNING,
            "note": "Estimates treat messages inside the window as free only when the length in force on the day of the click has been checked against Meta's own documentation. Add a change as a new dated row; rows are never edited."}


@router.post("/whatsapp/entry-windows", status_code=201)
def add_entry_window(body: EntryWindowIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    try:
        w = attribution.add_window(ctx.db, ctx.user, hours=body.hours, effective_from=body.effective_from, source=body.source, ip=client_ip(request))
        ctx.db.commit()
    except WaError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.detail())
    return attribution.serialize_window(ctx.db, w)


@router.post("/whatsapp/entry-windows/{window_id}/check", status_code=201)
def check_entry_window(window_id: uuid.UUID, body: VerifyIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Record a check of one window length against Meta's documentation. This adds a record; the row is never changed."""
    try:
        c = attribution.add_check(ctx.db, ctx.user, window_id, body.verified, body.note, ip=client_ip(request))
        ctx.db.commit()
    except WaError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.detail())
    return {"window_id": window_id, "verified": c.verified, "note": c.note, "at": c.created_at}
