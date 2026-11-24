"""Review Growth (tenant side): QR campaigns, review-link association, analytics and settings.

Everything is scoped to the caller's tenant via `get_tenant_context` (membership checked server-side, RLS as a second
layer). Writes need admin. Public customer endpoints live in review_public.py."""
import time
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, func, select

from app.api.v1.analytics import _fill, _range
from app.core.config import settings
from app.core.deps import TenantContext, get_tenant_context, require_role
from app.core.rate_limit import client_ip, hit
from app.models import GoogleConnection, GoogleConnectionStatus, Location, RetiredCampaignId, ReviewCampaign, ReviewSession, Role
from app.models.base import utcnow
from app.services.review_suggestions import (
    CATALOG, LANGUAGES, MAX_DESCRIPTION, MAX_SERVICES, category_options, merged_context, resolve_category, topics_for,
)
from app.schemas.review_growth import (
    AITestIn, ContextIn, CampaignCreateIn, CampaignOut, CampaignPatchIn, CampaignStats, Customization, DeactivateCodeIn, OldCode, ReviewUrlIn,
)
from app.services import entitlements as ent
from app.services import review_growth as svc
from app.services.ai import AIUnavailable, get_provider, privacy
from app.services.ai.base import configured_identity
from app.services.ai import health as ai_health
from app.services.ai.review_generate import NeedsMoreDetail, ReviewDraftRejected, ReviewInput, clean_field, generate_review
from app.services.ai_usage import log_generation, metered, usage_this_month
from app.services.audit import audit
from app.api.v1.qr import check_scannable, poster_response, qr_response, slug, style_for
from app.schemas.qr import QRStyleIn
from app.services.qr import campaign_url

router = APIRouter(prefix="/review-growth", tags=["review-growth"])
MAX_CAMPAIGNS = 50


def _own_location(ctx: TenantContext, location_id: uuid.UUID) -> Location:
    loc = ctx.db.scalar(select(Location).where(Location.id == location_id, Location.tenant_id == ctx.tenant_id))
    if not loc or not ctx.can_access_location(loc.id):
        raise HTTPException(status_code=404, detail="Location not found")
    return loc


def _own_campaign(ctx: TenantContext, campaign_id: uuid.UUID) -> ReviewCampaign:
    c = ctx.db.scalar(select(ReviewCampaign).where(ReviewCampaign.id == campaign_id, ReviewCampaign.tenant_id == ctx.tenant_id))
    if not c or not ctx.can_access_location(c.location_id):
        raise HTTPException(status_code=404, detail="Campaign not found")
    return c


def _out(ctx: TenantContext, c: ReviewCampaign, *, locs: dict | None = None, stats: dict | None = None) -> CampaignOut:
    loc = (locs or {}).get(c.location_id) if locs is not None else (ctx.db.get(Location, c.location_id) if c.location_id else None)
    url, source = svc.resolve_review_url(ctx.db, loc) if loc else (None, None)
    s = (stats or svc.campaign_stats(ctx.db, [c.id])).get(c.id, {})
    old = [OldCode(public_id=o.public_id, url=campaign_url(o.public_id), retired_at=o.retired_at, active=o.deactivated_at is None, deactivated_at=o.deactivated_at)
           for o in ctx.db.scalars(select(RetiredCampaignId).where(RetiredCampaignId.campaign_id == c.id).order_by(RetiredCampaignId.retired_at.desc()))] if c.qr_rotated_at else []
    return CampaignOut(
        id=c.id, name=c.name, status=c.status, location_id=c.location_id, location_name=loc.name if loc else None,
        public_id=c.public_id, url=campaign_url(c.public_id), customization=Customization.model_validate(c.customization or {}),
        review_url_ready=bool(url), review_url_source=source, stats=CampaignStats(**s), created_at=c.created_at,
        updated_at=c.updated_at, qr_rotated_at=c.qr_rotated_at, qr_style=QRStyleIn.model_validate(c.qr_style) if c.qr_style else None,
        retired_codes=len(old), old_codes=old,
    )


@router.get("/campaigns", response_model=list[CampaignOut])
def list_campaigns(include_archived: bool = False, ctx: TenantContext = Depends(get_tenant_context)):
    q = select(ReviewCampaign).where(ReviewCampaign.tenant_id == ctx.tenant_id, ctx.scope(ReviewCampaign.location_id)).order_by(ReviewCampaign.created_at.desc())
    if not include_archived:
        q = q.where(ReviewCampaign.status != "archived")
    rows = ctx.db.scalars(q).all()
    locs = {l.id: l for l in ctx.db.scalars(select(Location).where(Location.tenant_id == ctx.tenant_id, ctx.scope(Location.id)))}
    stats = svc.campaign_stats(ctx.db, [c.id for c in rows])
    return [_out(ctx, c, locs=locs, stats=stats) for c in rows]


@router.post("/campaigns", response_model=CampaignOut, status_code=201)
def create_campaign(body: CampaignCreateIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    ent.require_active(ctx.db, ctx.tenant_id)
    loc = _own_location(ctx, body.location_id)
    if not loc.is_active:
        raise HTTPException(status_code=400, detail="This location is deactivated")
    live = ctx.db.scalar(select(func.count()).select_from(ReviewCampaign).where(ReviewCampaign.tenant_id == ctx.tenant_id, ReviewCampaign.status != "archived"))
    if (live or 0) >= MAX_CAMPAIGNS:
        raise HTTPException(status_code=400, detail=f"You can have up to {MAX_CAMPAIGNS} active campaigns. Archive some to create more.")
    c = ReviewCampaign(tenant_id=ctx.tenant_id, location_id=loc.id, name=body.name, public_id=svc.issue_public_id(ctx.db), status="active",
                       customization=(body.customization or Customization()).model_dump(), created_by=ctx.user.id)
    ctx.db.add(c)
    ctx.db.flush()
    audit(ctx.db, action="review_campaign.create", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="review_campaign",
          entity_id=c.id, ip=client_ip(request))
    ctx.db.commit()
    return _out(ctx, c)


@router.get("/campaigns/{campaign_id}", response_model=CampaignOut)
def get_campaign(campaign_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    return _out(ctx, _own_campaign(ctx, campaign_id))


@router.patch("/campaigns/{campaign_id}", response_model=CampaignOut)
def update_campaign(campaign_id: uuid.UUID, body: CampaignPatchIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    c = _own_campaign(ctx, campaign_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("status") == "active" and c.status != "active":
        ent.require_active(ctx.db, ctx.tenant_id)
    if "location_id" in data and data["location_id"] is not None and data["location_id"] != c.location_id:
        # Editing the destination: the printed code and its link stay exactly the same, only where it leads changes.
        target = _own_location(ctx, data["location_id"])
        if not target.is_active:
            raise HTTPException(status_code=400, detail="This location is deactivated. Reactivate it first, or choose another location, so the QR code keeps working.")
        c.location_id = target.id
    if "name" in data and data["name"]:
        c.name = data["name"]
    if "customization" in data and data["customization"] is not None:
        c.customization = body.customization.model_dump()
    if "qr_style" in data:  # visual only: the code keeps encoding the same permanent link
        if body.qr_style is None:
            c.qr_style = None
        else:
            style = body.qr_style.model_dump()
            _, logo = style_for(ctx.db, ctx.tenant_id)
            if style["use_logo"] and logo is None:
                raise HTTPException(status_code=422, detail="Upload a logo in QR settings first, then turn it on")
            check_scannable(campaign_url(c.public_id), style, logo)
            c.qr_style = style
    if "status" in data and data["status"] is not None and data["status"] != c.status:
        c.status = data["status"]
        c.archived_at = utcnow() if c.status == "archived" else None
    audit(ctx.db, action="review_campaign.update", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="review_campaign",
          entity_id=c.id, meta={"fields": sorted(data)}, ip=client_ip(request))
    ctx.db.commit()
    return _out(ctx, c)


@router.delete("/campaigns/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: uuid.UUID, request: Request, permanent: bool = False, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Archive (default: the QR stops working, analytics are kept). `?permanent=true` erases an ARCHIVED campaign and all its
    sessions, drafts and events; owners only."""
    c = _own_campaign(ctx, campaign_id)
    if permanent:
        if ctx.role != Role.owner:
            raise HTTPException(status_code=403, detail="Only the owner can permanently delete a campaign")
        if c.status != "archived":
            raise HTTPException(status_code=409, detail="Archive the campaign first, then delete it permanently")
        ctx.db.execute(delete(ReviewCampaign).where(ReviewCampaign.id == c.id))
        audit(ctx.db, action="review_campaign.delete", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="review_campaign",
              entity_id=c.id, ip=client_ip(request))
    else:
        c.status, c.archived_at = "archived", utcnow()
        audit(ctx.db, action="review_campaign.archive", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="review_campaign",
              entity_id=c.id, ip=client_ip(request))
    ctx.db.commit()


MAX_OLD_CODES = 20


@router.post("/campaigns/{campaign_id}/regenerate-qr", response_model=CampaignOut)
def regenerate_qr(campaign_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Issue a NEW code for the campaign. The previous code is kept as an alias: copies already printed keep working and
    open the same campaign. Nothing is invalidated here; switching an old code off is a separate, explicit action
    (`.../codes/{public_id}/deactivate`). Sessions, drafts and analytics stay attached to the campaign."""
    c = _own_campaign(ctx, campaign_id)
    if c.status == "archived":
        raise HTTPException(status_code=409, detail="Restore the campaign before issuing a new QR code")
    have = ctx.db.scalar(select(func.count()).select_from(RetiredCampaignId).where(RetiredCampaignId.campaign_id == c.id)) or 0
    if have >= MAX_OLD_CODES:
        raise HTTPException(status_code=409, detail=f"This campaign already has {MAX_OLD_CODES} earlier codes. Create a new campaign instead.")
    old = c.public_id
    ctx.db.add(RetiredCampaignId(tenant_id=ctx.tenant_id, campaign_id=c.id, public_id=old, retired_by=ctx.user.id, retired_at=utcnow()))
    c.public_id, c.qr_rotated_at = svc.issue_public_id(ctx.db), utcnow()
    audit(ctx.db, action="review_campaign.new_code", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="review_campaign",
          entity_id=c.id, meta={"previous_id_prefix": old[:6], "previous_code_kept": True}, ip=client_ip(request))
    ctx.db.commit()
    return _out(ctx, c)


def _old_code(ctx: TenantContext, c: ReviewCampaign, public_id: str) -> RetiredCampaignId:
    row = ctx.db.scalar(select(RetiredCampaignId).where(RetiredCampaignId.campaign_id == c.id, RetiredCampaignId.public_id == public_id))
    if not row:
        raise HTTPException(status_code=404, detail="That is not an earlier code of this campaign")
    return row


@router.post("/campaigns/{campaign_id}/codes/{public_id}/deactivate", response_model=CampaignOut)
def deactivate_old_code(campaign_id: uuid.UUID, public_id: str, body: DeactivateCodeIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Switch off ONE earlier code (e.g. it leaked). This is the only action that stops a printed code while its campaign
    is live, it never happens as a side effect of anything else, and it needs {"confirm": "DEACTIVATE"}. The campaign's
    current code and its other earlier codes are not affected."""
    c = _own_campaign(ctx, campaign_id)
    row = _old_code(ctx, c, public_id)
    if row.deactivated_at is None:
        row.deactivated_at = utcnow()
        audit(ctx.db, action="review_campaign.code_deactivate", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="review_campaign",
              entity_id=c.id, meta={"id_prefix": public_id[:6]}, ip=client_ip(request))
        ctx.db.commit()
    return _out(ctx, c)


@router.post("/campaigns/{campaign_id}/codes/{public_id}/reactivate", response_model=CampaignOut)
def reactivate_old_code(campaign_id: uuid.UUID, public_id: str, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Undo a deactivation: the same printed code works again (its id was never given to anything else)."""
    c = _own_campaign(ctx, campaign_id)
    row = _old_code(ctx, c, public_id)
    if row.deactivated_at is not None:
        row.deactivated_at = None
        audit(ctx.db, action="review_campaign.code_reactivate", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="review_campaign",
              entity_id=c.id, meta={"id_prefix": public_id[:6]}, ip=client_ip(request))
        ctx.db.commit()
    return _out(ctx, c)


@router.get("/campaigns/{campaign_id}/qr.{fmt}")
def campaign_qr(campaign_id: uuid.UUID, fmt: str, size: int | None = Query(None, ge=256, le=4096), ctx: TenantContext = Depends(require_role(Role.admin))):
    """The campaign's code as PNG, SVG or PDF, drawn in the campaign's style (or the business's). Always encodes the
    campaign's current permanent link; downloading never changes it."""
    c = _own_campaign(ctx, campaign_id)
    style, logo = style_for(ctx.db, ctx.tenant_id, c.qr_style)
    return qr_response(campaign_url(c.public_id), fmt, style, logo, f"flowqr-{slug(c.name, 'campaign')}", size_px=size)


@router.get("/campaigns/{campaign_id}/poster.{fmt}")
def campaign_poster(campaign_id: uuid.UUID, fmt: str, scale: int = Query(1, ge=1, le=3), size: str = Query("ref"),
                    ctx: TenantContext = Depends(require_role(Role.admin))):
    """The approved FlowQR review poster with this campaign's permanent code in it (PNG, SVG or print-ready PDF).
    Only the code differs between businesses and campaigns. Downloading never changes the campaign's link."""
    c = _own_campaign(ctx, campaign_id)
    return poster_response(campaign_url(c.public_id), fmt, f"flowqr-{slug(c.name, 'campaign')}", scale=scale, size=size)


@router.post("/locations/{location_id}/review-url")
def set_review_url(location_id: uuid.UUID, body: ReviewUrlIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Attach the Google review link used by every campaign at this location. Either an admin-entered Google link (host-checked)
    or the link from the connected Business Profile location. We never post reviews through any API."""
    loc = _own_location(ctx, location_id)
    if body.use_google:
        url, _ = svc.google_review_url(ctx.db, loc)
        if not url:
            raise HTTPException(status_code=404, detail={"code": "no_google_link", "message": "No connected Google location with a review link is mapped to this location yet. Connect Google and select the location, or paste the link manually."})
        loc.review_url, loc.review_url_source = url, "google"
    else:
        loc.review_url, loc.review_url_source = body.url, "manual"
    audit(ctx.db, action="review_campaign.review_url", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="location",
          entity_id=loc.id, meta={"source": loc.review_url_source}, ip=client_ip(request))
    ctx.db.commit()
    return {"review_url": loc.review_url, "source": loc.review_url_source}


@router.get("/analytics")
def analytics(ctx: TenantContext = Depends(get_tenant_context), start: date | None = Query(None, alias="from"),
              end: date | None = Query(None, alias="to"), campaign_id: uuid.UUID | None = None, location_id: uuid.UUID | None = None):
    if campaign_id:
        _own_campaign(ctx, campaign_id)
    if location_id:
        _own_location(ctx, location_id)
    start, end, lo, hi, tz = _range(ctx, start, end)
    allowed = None
    if ctx.restricted:  # restricted staff: only campaigns at their locations, in totals as well as in the list
        allowed = list(ctx.db.scalars(select(ReviewCampaign.id).where(ReviewCampaign.tenant_id == ctx.tenant_id, ctx.scope(ReviewCampaign.location_id))))
    return svc.analytics(ctx.db, tenant_id=ctx.tenant_id, tz=tz, start=start, end=end, lo=lo, hi=hi, campaign_id=campaign_id, fill=_fill,
                         campaign_ids=allowed, location_id=location_id)


def _context_payload(tenant, preview_category: str | None = None) -> dict:
    rc = tenant.review_context or {}
    key = preview_category if preview_category in CATALOG else resolve_category(tenant.category, rc.get("category_key"))  # preview: see another category's topics before saving
    disabled = set(rc.get("disabled_suggestions") or [])
    languages = [l for l in (rc.get("languages") or LANGUAGES) if l in LANGUAGES] or list(LANGUAGES)
    return {
        "tenant_category": tenant.category, "detected_category": resolve_category(tenant.category), "category_key": key,
        "category_override": rc.get("category_key"), "categories": category_options(),
        "description": rc.get("description", ""), "services": rc.get("services", []), "languages": languages,
        "suggestions": [{"id": t.id, "en": t.en, "hi": t.hi, "enabled": t.id not in disabled} for t in topics_for(key)],
        "limits": {"description": MAX_DESCRIPTION, "services": MAX_SERVICES},
        "notes": [
            "This tells the AI what your business offers. It is never treated as evidence of what a particular customer experienced.",
            "Suggestions are topics customers can comment on, not claims. Customers pick only what applies and say whether it was good, okay or not good.",
            "Claims such as “best”, “guaranteed”, “cure”, prices and links are not accepted.",
        ],
    }


@router.get("/context")
def get_context(preview_category: str | None = None, ctx: TenantContext = Depends(get_tenant_context)):
    return _context_payload(ctx.tenant, preview_category)


@router.put("/context")
def put_context(body: ContextIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Owner-configured business context: category, plain description, services/products, enabled topic chips and supported languages."""
    key = resolve_category(ctx.tenant.category, body.category_key)
    valid = {t.id for t in topics_for(key)}
    ctx.tenant.review_context = {
        "category_key": body.category_key, "description": body.description or "", "services": body.services,
        "disabled_suggestions": [s for s in body.disabled_suggestions if s in valid], "languages": body.languages,
    }
    audit(ctx.db, action="review_context.update", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="tenant", entity_id=ctx.tenant_id,
          meta={"category": key, "services": len(body.services), "disabled": len(ctx.tenant.review_context["disabled_suggestions"])}, ip=client_ip(request))
    ctx.db.commit()
    return _context_payload(ctx.tenant)


@router.post("/ai/test")
def test_ai(body: AITestIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Run ONE real generation through the configured provider and the same anti-fabrication checks customers get, and report what
    happened: model, latency, tokens and the guardrail verdict. For admins diagnosing the AI setup; customers never see this."""
    ent.require_active(ctx.db, ctx.tenant_id)
    if not hit(f"ai-test:{ctx.tenant_id}", 10, 3600):
        raise HTTPException(status_code=429, detail="You can run up to 10 AI tests per hour.")
    inp = ReviewInput(note=clean_field(body.text, 1200), rating=body.rating)
    name, model = configured_identity()
    out: dict = {"ok": False, "provider": name, "model": model, "model_served": None, "language": body.language, "style": body.style,
                 "latency_ms": None, "tokens": None, "draft": None, "rejected_text": None, "checks": None, "error": None}
    started, provider, status, err = time.monotonic(), None, "error", None
    try:
        provider = metered(get_provider(), ctx.db, ctx.tenant_id, "review_test")
        text = generate_review(provider, inp, language=body.language, style=body.style, business_name=ctx.tenant.name, category=ctx.tenant.category)
        out.update(ok=True, draft=text, checks={"passed": True, "reason": None, "fact_check": settings.review_verify_with_ai})
        status = "ok"
        ai_health.clear()  # a working test proves the provider is back (e.g. after credits were added)
    except NeedsMoreDetail:
        out["error"] = {"code": "needs_more", "message": "The sample words are too vague to write a truthful review."}
        status = "needs_more"
    except ReviewDraftRejected as exc:
        out.update(rejected_text=(exc.text or "")[:1500], checks={"passed": False, "reason": exc.reason, "unsupported": exc.detail, "fact_check": settings.review_verify_with_ai}, error={"code": "rejected", "message": f"The model's draft failed a faithfulness check: {exc.reason}."})
        status, err = "rejected", exc.reason
    except AIUnavailable as exc:
        out["error"] = {"code": exc.code, "message": str(exc)}
        err = f"{exc.code}: {exc}"
        ai_health.mark_down(exc.code, exc.retry_after)
    usage = getattr(provider, "usage", None)
    out["latency_ms"] = int((time.monotonic() - started) * 1000)
    if usage and usage.get("calls"):
        out["tokens"] = {"prompt": usage["prompt_tokens"], "completion": usage["completion_tokens"], "calls": usage["calls"]}
        out["model_served"] = usage.get("model")
    log_generation(ctx.db, tenant_id=ctx.tenant_id, kind="review_test", provider=provider.name if provider else name, model=provider.model if provider else model,
                   language=body.language, input_chars=len(inp.text()), output_chars=len(out["draft"] or ""), status=status, started=started,
                   error=err, usage=usage)
    ctx.db.commit()
    return out


@router.get("/settings")
def review_growth_settings(ctx: TenantContext = Depends(get_tenant_context)):
    e = ent.for_tenant(ctx.db, ctx.tenant_id)
    locs = ctx.db.scalars(select(Location).where(Location.tenant_id == ctx.tenant_id, Location.is_active.is_(True))).all()
    connected = ctx.db.scalar(select(func.count()).select_from(GoogleConnection).where(
        GoogleConnection.tenant_id == ctx.tenant_id, GoogleConnection.status == GoogleConnectionStatus.active)) or 0
    return {
        "ai": {"configured": settings.ai_configured, "review_data_blocked": privacy.blocked_now(), "provider": settings.ai_provider if settings.ai_configured else None,
               "model": configured_identity()[1] if settings.ai_configured else None, "degraded": ai_health.current(),
               "used_this_month": usage_this_month(ctx.db, ctx.tenant_id), "monthly_limit": e.monthly_ai_generations},
        "limits": {"max_drafts_per_customer": min(settings.review_max_drafts_per_session, settings.review_max_ai_writes_per_session), "max_campaigns": MAX_CAMPAIGNS},
        "retention_days": settings.review_session_retention_days,
        "google_connected": connected > 0,
        "locations": [{"id": str(l.id), "name": l.name, "review_url": l.review_url, "review_url_source": l.review_url_source if l.review_url else None,
                       "google_link_available": bool(svc.google_review_url(ctx.db, l)[0]),
                       "review_url_kind": svc.review_url_kind(svc.resolve_review_url(ctx.db, l)[0])} for l in locs],  # direct | listing | unknown | none: what customers will actually be sent to
        "principles": [
            "Every draft is built only from what the customer wrote. The AI is told not to add facts, and the output is checked for invented numbers, names, ratings and claims.",
            "Customers always see, edit and approve the text. We never submit anything to Google for them: the review is copied to their clipboard and Google opens, and they paste and post it themselves.",
            "Every customer gets the same flow regardless of rating or sentiment. Nothing is filtered or routed.",
            "No rewards or incentives are offered for reviews.",
        ],
    }
