"""Reusable review-request templates (PRD: Review Growth). A template is a short, neutral message a business sends to EVERY customer
(WhatsApp, SMS, email, or a printed line), with the campaign link filled in.

Neutral by rule, checked on every save: no incentive or reward, no mention of stars or ratings, no "only if you were happy", nothing that
steers unhappy customers elsewhere. The same message goes to everyone; FlowQR never chooses who receives it."""
import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.deps import TenantContext, get_tenant_context, require_role
from app.core.rate_limit import client_ip
from app.models import Location, ReviewCampaign, ReviewRequestTemplate, Role
from app.services.audit import audit
from app.services.qr import campaign_url

router = APIRouter(prefix="/review-growth/templates", tags=["review-growth"])

# Words that turn a request into an incentive or a filter (English, Hindi, Hinglish). Matched case-insensitively on word boundaries.
BLOCKED = [
    (r"discount|% ?off|cash ?back|voucher|coupon|gift|reward|prize|lucky draw|freebie|for free|free (gift|service|session|consultation|treatment|meal|coffee|drink)|special offer|incentive", "Offers or rewards for reviews aren't allowed by Google."),
    (r"\b5[ -]?star|five[ -]?star|\b\d ?stars?\b|★|⭐|rating of|rate us", "Don't ask for a particular rating. Ask everyone the same neutral question."),
    (r"only if|if you (were|are) (happy|satisfied)|if you (liked|loved|enjoyed)|positive review|good review|great review|nice review|happy customers", "Ask every customer equally, not only happy ones."),
    (r"if (you were|you are) (unhappy|not happy|dissatisfied)|instead of (google|reviewing)|contact us (first|before)", "Don't steer unhappy customers away from reviewing."),
    (r"छूट|मुफ्त|मुफ़्त|इनाम|उपहार|कूपन|5 स्टार|पांच स्टार|पाँच स्टार|अच्छा रिव्यू|अच्छी समीक्षा", "Offers, rewards or asking for a good rating aren't allowed."),
    (r"\bmuft\b|\binaam\b|accha review|achha review|acchi review", "Offers, rewards or asking for a good rating aren't allowed."),
]
PLACEHOLDERS = {"{customer}", "{business}", "{link}"}

PRESETS = [
    {"name": "WhatsApp after a visit", "channel": "whatsapp", "language": "en",
     "body": "Hi {customer}, thank you for visiting {business}. We'd value your honest feedback on Google; it takes a minute: {link}"},
    {"name": "SMS (short)", "channel": "sms", "language": "en", "body": "Thanks for choosing {business}. Please share your honest experience on Google: {link}"},
    {"name": "WhatsApp (Hindi)", "channel": "whatsapp", "language": "hi",
     "body": "नमस्ते {customer}, {business} आने के लिए धन्यवाद। कृपया Google पर अपना सच्चा अनुभव साझा करें: {link}"},
    {"name": "WhatsApp (Hinglish)", "channel": "whatsapp", "language": "hinglish",
     "body": "Hi {customer}, {business} aane ke liye thank you! Apna honest experience Google par share karein: {link}"},
    {"name": "Printed line (bill or counter)", "channel": "print", "language": "en", "body": "Tell us how we did: scan the code or visit {link}"},
]


def problems(body: str) -> list[str]:
    out = []
    low = body.lower()
    for pat, msg in BLOCKED:
        if re.search(pat, low, re.I) and msg not in out:
            out.append(msg)
    if "{link}" not in body:
        out.append("Include {link} so customers can reach the review page.")
    unknown = set(re.findall(r"\{[a-z_]+\}", body)) - PLACEHOLDERS
    if unknown:
        out.append("Unknown placeholder: " + ", ".join(sorted(unknown)) + ". Use {customer}, {business} or {link}.")
    return out


class TemplateIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    channel: Literal["whatsapp", "sms", "email", "print"] = "whatsapp"
    language: Literal["en", "hi", "hinglish"] = "en"
    body: str = Field(min_length=10, max_length=700)


def _out(t: ReviewRequestTemplate) -> dict:
    return {"id": str(t.id), "name": t.name, "channel": t.channel, "language": t.language, "body": t.body, "created_at": t.created_at, "updated_at": t.updated_at}


def _check(body: str) -> None:
    if p := problems(body):
        raise HTTPException(status_code=422, detail={"code": "not_neutral", "message": " ".join(p), "problems": p})


@router.get("")
def list_templates(ctx: TenantContext = Depends(get_tenant_context)):
    rows = ctx.db.scalars(select(ReviewRequestTemplate).where(ReviewRequestTemplate.tenant_id == ctx.tenant_id).order_by(ReviewRequestTemplate.created_at)).all()
    ctx.db.commit()
    return {"templates": [_out(t) for t in rows], "presets": PRESETS, "placeholders": sorted(PLACEHOLDERS)}


@router.post("", status_code=201)
def create(body: TemplateIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _check(body.body)
    t = ReviewRequestTemplate(tenant_id=ctx.tenant_id, name=body.name.strip(), channel=body.channel, language=body.language, body=body.body.strip(), created_by=ctx.user.id)
    ctx.db.add(t)
    ctx.db.flush()
    audit(ctx.db, action="review_template.create", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="review_request_template", entity_id=t.id, ip=client_ip(request))
    ctx.db.commit()
    return _out(t)


def _get(ctx: TenantContext, tid: uuid.UUID) -> ReviewRequestTemplate:
    t = ctx.db.scalar(select(ReviewRequestTemplate).where(ReviewRequestTemplate.id == tid, ReviewRequestTemplate.tenant_id == ctx.tenant_id))
    if not t:
        raise HTTPException(status_code=404, detail="Template not found")
    return t


@router.put("/{template_id}")
def update(template_id: uuid.UUID, body: TemplateIn, ctx: TenantContext = Depends(require_role(Role.admin))):
    t = _get(ctx, template_id)
    _check(body.body)
    t.name, t.channel, t.language, t.body = body.name.strip(), body.channel, body.language, body.body.strip()
    ctx.db.commit()
    return _out(t)


@router.delete("/{template_id}", status_code=204)
def delete(template_id: uuid.UUID, ctx: TenantContext = Depends(require_role(Role.admin))):
    ctx.db.delete(_get(ctx, template_id))
    ctx.db.commit()


class RenderIn(BaseModel):
    campaign_id: uuid.UUID
    customer: str | None = Field(default=None, max_length=60)


@router.post("/{template_id}/render")
def render(template_id: uuid.UUID, body: RenderIn, ctx: TenantContext = Depends(get_tenant_context)):
    """The message with the campaign's link filled in, ready to copy or open in WhatsApp. FlowQR sends nothing itself."""
    t = _get(ctx, template_id)
    c = ctx.db.scalar(select(ReviewCampaign).where(ReviewCampaign.id == body.campaign_id, ReviewCampaign.tenant_id == ctx.tenant_id))
    if not c or not ctx.can_access_location(c.location_id) or c.status != "active":
        raise HTTPException(status_code=404, detail="Active campaign not found")
    loc = ctx.db.get(Location, c.location_id) if c.location_id else None
    text = (t.body.replace("{customer}", (body.customer or "").strip() or "there").replace("{business}", ctx.tenant.name + (f" {loc.name}" if loc and loc.name.lower() not in ctx.tenant.name.lower() else ""))
            .replace("{link}", campaign_url(c.public_id)))
    ctx.db.commit()
    return {"text": text, "link": campaign_url(c.public_id), "channel": t.channel}
