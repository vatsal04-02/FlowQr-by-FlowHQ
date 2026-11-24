"""Google Marketing Studio API: campaigns, the media/document library, the local SEO assistant and publishing readiness.

Approving, scheduling, cancelling and retrying a post stay on /posts (the governed engine); this router only plans, writes, organises and reports. Every query is scoped to the
signed-in business (row-level security plus an explicit tenant filter) and to the locations the member may access.
"""
import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.config import settings
from app.core.deps import TenantContext, get_tenant_context, require_role
from app.core.rate_limit import client_ip, hit
from app.models import AgentAction, GoogleConnection, GoogleConnectionStatus, GoogleLocation, MarketingAsset, MarketingCampaign, Role, ScheduledPost
from app.models.base import utcnow
from app.models.marketing import DURATIONS, OBJECTIVES
from app.services import entitlements as ent
from app.services import marketing_studio as studio
from app.services.agent import controls
from app.services.agent import knowledge as kbs
from app.services.agent import posts as post_svc
from app.services.ai import AIUnavailable, get_provider, intelligence
from app.services.ai_usage import log_generation, metered, quota_exceeded
from app.services.audit import audit
from app.services.google.provider import has_business_scope

log = logging.getLogger("flowqr.marketing.api")
router = APIRouter(prefix="/marketing", tags=["marketing"])

MAX_UPLOAD = 10 * 1024 * 1024


class CampaignIn(BaseModel):
    google_location_id: uuid.UUID
    brief: str = Field(min_length=10, max_length=1500)
    objective: Literal[OBJECTIVES]
    duration_days: Literal[7, 15, 30]
    start_date: date | None = None
    language: str | None = Field(default=None, pattern="^(en|hi|hinglish)$")
    asset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=12)
    event_title: str | None = Field(default=None, max_length=58)
    event_start: datetime | None = None
    event_end: datetime | None = None


class RescheduleIn(BaseModel):
    scheduled_for: datetime | None = None  # a future time (naive values are read in the business's time zone); omit to publish now


class AssetPostIn(BaseModel):
    asset_id: uuid.UUID | None = None  # None removes the photo


def _need(ctx: TenantContext) -> None:
    ent.require_feature(ctx.db, ctx.tenant_id, "gbp_posts")


def _gloc(ctx: TenantContext, gid: uuid.UUID) -> GoogleLocation:
    gl = ctx.db.scalar(select(GoogleLocation).where(GoogleLocation.id == gid, GoogleLocation.tenant_id == ctx.tenant_id))
    if not gl or not gl.selected or not ctx.can_access_location(gl.location_id):
        raise HTTPException(status_code=404, detail="Google location not found")
    return gl


def _campaign(ctx: TenantContext, cid: uuid.UUID) -> MarketingCampaign:
    c = ctx.db.scalar(select(MarketingCampaign).where(MarketingCampaign.id == cid, MarketingCampaign.tenant_id == ctx.tenant_id))
    gl = ctx.db.get(GoogleLocation, c.google_location_id) if c else None
    if not c or not gl or not ctx.can_access_location(gl.location_id):
        raise HTTPException(status_code=404, detail="Campaign not found")
    return c


def _asset(ctx: TenantContext, aid: uuid.UUID) -> MarketingAsset:
    a = ctx.db.scalar(select(MarketingAsset).where(MarketingAsset.id == aid, MarketingAsset.tenant_id == ctx.tenant_id))
    if not a:
        raise HTTPException(status_code=404, detail="File not found")
    return a


def _wrap(fn):
    try:
        return fn()
    except studio.StudioError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    except post_svc.PostError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


def _asset_out(a: MarketingAsset, warnings: list[str] | None = None) -> dict:
    out = {"id": str(a.id), "kind": a.kind, "file_name": a.file_name, "label": a.label, "content_type": a.content_type, "size_bytes": a.size_bytes, "width": a.width, "height": a.height,
           "created_at": a.created_at, "readable": bool(a.text_excerpt) if a.kind == "document" else None}
    if warnings:
        out["warnings"] = warnings
    return out


def _post_out(ctx: TenantContext, p: ScheduledPost, kb: dict) -> dict:
    from app.api.v1 import posts as posts_api
    return posts_api._out(ctx, p, kb)


def _campaign_out(c: MarketingCampaign, counts: dict | None = None) -> dict:
    return {"id": str(c.id), "google_location_id": str(c.google_location_id), "title": c.title, "brief": c.brief, "objective": c.objective, "objective_label": studio.OBJECTIVE_LABELS[c.objective],
            "duration_days": c.duration_days, "start_date": c.start_date.isoformat(), "language": c.language, "status": c.status, "event_title": c.event_title, "event_start": c.event_start,
            "event_end": c.event_end, "asset_ids": c.asset_ids or [], "notes": c.notes or [], "keywords": c.keywords or [], "created_at": c.created_at, "counts": counts or {}}


# post state -> the five numbers the owner cares about
def _bucket(status: str) -> str:
    return {"awaiting_approval": "generated", "draft": "draft", "approved": "approved", "scheduled": "scheduled", "publishing": "scheduled", "published": "published", "failed": "failed",
            "canceled": "canceled"}[status]


def _counts(ctx: TenantContext, campaign_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    out: dict[uuid.UUID, dict] = {i: {} for i in campaign_ids}
    if not campaign_ids:
        return out
    for cid, st, n in ctx.db.execute(select(ScheduledPost.campaign_id, ScheduledPost.status, func.count()).where(ScheduledPost.tenant_id == ctx.tenant_id, ScheduledPost.campaign_id.in_(campaign_ids))
                                     .group_by(ScheduledPost.campaign_id, ScheduledPost.status)).all():
        b = _bucket(st)
        out[cid][b] = out[cid].get(b, 0) + n
        out[cid]["total"] = out[cid].get("total", 0) + n
    return out


# ------------------------------------------------------------------ overview & readiness
@router.get("/overview")
def overview(ctx: TenantContext = Depends(get_tenant_context)):
    campaigns = ctx.db.scalar(select(func.count()).select_from(MarketingCampaign).join(GoogleLocation, GoogleLocation.id == MarketingCampaign.google_location_id).where(
        MarketingCampaign.tenant_id == ctx.tenant_id, MarketingCampaign.status != "archived", ctx.scope(GoogleLocation.location_id))) or 0
    rows = ctx.db.execute(select(ScheduledPost.status, func.count()).join(GoogleLocation, GoogleLocation.id == ScheduledPost.google_location_id).where(
        ScheduledPost.tenant_id == ctx.tenant_id, ScheduledPost.campaign_id.is_not(None), ctx.scope(GoogleLocation.location_id)).group_by(ScheduledPost.status)).all()
    by = {st: n for st, n in rows}
    return {"campaigns": campaigns, "generated_posts": sum(by.values()) - by.get("canceled", 0), "awaiting_review": by.get("awaiting_approval", 0) + by.get("draft", 0),
            "approved": by.get("approved", 0), "scheduled": by.get("scheduled", 0) + by.get("publishing", 0), "published": by.get("published", 0), "failed": by.get("failed", 0),
            "canceled": by.get("canceled", 0)}


@router.get("/readiness")
def readiness(google_location_id: uuid.UUID | None = None, ctx: TenantContext = Depends(get_tenant_context)):
    """Can this business publish a Google post right now, and if not, exactly what is missing? Reports what FlowQR knows; it never makes a Google call and never publishes."""
    conn = ctx.db.scalar(select(GoogleConnection).where(GoogleConnection.tenant_id == ctx.tenant_id).order_by(GoogleConnection.created_at.desc()))
    gl = ctx.db.scalar(select(GoogleLocation).where(GoogleLocation.id == google_location_id, GoogleLocation.tenant_id == ctx.tenant_id)) if google_location_id else None
    checks = []

    def add(key, label, ok, detail, action=None):
        checks.append({"key": key, "label": label, "ok": bool(ok), "detail": detail, "action": action})

    connected = bool(conn and conn.status == GoogleConnectionStatus.active)
    add("connection", "Google Business Profile connected", connected, "Connected." if connected else "Connect your Google Business Profile to publish.", None if connected else "/gbp/connect")
    scope_ok = bool(conn and has_business_scope(conn.scopes))
    add("scope", "Permission to manage your profile (business.manage)", scope_ok if conn else False, "Granted." if scope_ok else "Reconnect Google and allow the Business Profile permission.", None if scope_ok else "/gbp/connect")
    api = (conn.api_access if conn else "unknown") or "unknown"
    add("api", "Google's Business Profile API access", api not in ("api_disabled", "awaiting_approval"),
        {"api_disabled": "The Business Profile APIs are switched off on FlowQR's Google project. FlowQR support must enable them.", "awaiting_approval": "Google has not yet approved FlowQR's API access (quota 0).",
         "unknown": "Not checked yet: press Re-check on the Google connection page.", "ok": "Working."}.get(api, "Working."))
    add("location", "A selected business location", bool(gl and gl.selected) if gl else bool(ctx.db.scalar(select(func.count()).select_from(GoogleLocation).where(GoogleLocation.tenant_id == ctx.tenant_id, GoogleLocation.selected.is_(True)))),
        "Selected." , "/gbp/locations")
    try:
        get_provider()
        ai = True
    except AIUnavailable:
        ai = False
    add("ai", "AI writing is available", ai, "Ready." if ai else "No AI provider is configured on this server.")
    base = settings.api_public_url or ""
    add("photo_url", "A public address for post photos", base.startswith("https://"), "Photos can be attached." if base.startswith("https://") else "Posts can be published without photos only (API_PUBLIC_URL is not an https address).")
    stop = controls.emergency_stop(ctx.db) or settings.autonomy_emergency_stop
    add("stop", "Publishing is not paused platform-wide", not stop, "Not paused." if not stop else "Publishing is paused by FlowQR for everyone. Posts wait until it is lifted.")
    publish_ok = all(c["ok"] for c in checks if c["key"] in ("connection", "scope", "api", "location", "stop"))
    return {"can_publish": publish_ok, "checks": checks,
            "statement": ("FlowQR can send an approved post to Google. The first live post still needs checking on your own profile." if publish_ok else "Publishing is not ready: fix the items marked below."),
            "approval_required": True}


# ------------------------------------------------------------------ SEO assistant
@router.get("/seo-assistant")
def seo_assistant(google_location_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    _need(ctx)
    gl = _gloc(ctx, google_location_id)
    kb = kbs.context(ctx.db, ctx.tenant)
    intel = intelligence.build(ctx.db, ctx.tenant, kb, google_location_id=gl.id)
    ctx.db.commit()
    return studio.seo_assistant(ctx.db, ctx.tenant, gl, kb, intel)


# ------------------------------------------------------------------ library
@router.get("/assets")
def list_assets(kind: Literal["image", "document"] | None = None, ctx: TenantContext = Depends(get_tenant_context)):
    q = select(MarketingAsset).where(MarketingAsset.tenant_id == ctx.tenant_id).order_by(MarketingAsset.created_at.desc()).limit(200)
    if kind:
        q = q.where(MarketingAsset.kind == kind)
    rows = ctx.db.scalars(q).all()
    used = {a for (a,) in ctx.db.execute(select(ScheduledPost.asset_id).where(ScheduledPost.tenant_id == ctx.tenant_id, ScheduledPost.asset_id.is_not(None))).all()}
    return {"assets": [{**_asset_out(a), "in_use": a.id in used} for a in rows]}


@router.post("/assets", status_code=201)
async def upload_asset(request: Request, kind: Literal["image", "document"] = Query(), file_name: str = Query(max_length=200), label: str | None = Query(None, max_length=200),
                       ctx: TenantContext = Depends(get_tenant_context)):
    """Add an image (JPG/PNG) or a document (PDF, Word, text). Send the file's bytes as the request body."""
    ent.require_active(ctx.db, ctx.tenant_id)
    _need(ctx)
    if not hit(f"mkt-upload:{ctx.tenant_id}", 60, 3600):
        raise HTTPException(status_code=429, detail="Too many uploads this hour. Try again later.")
    cap = studio.photo_rules.MAX_BYTES if kind == "image" else studio.MAX_DOC_BYTES
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > cap:
        raise HTTPException(status_code=413, detail=f"This file is too large (the limit is {cap // 1048576} MB).")
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > cap:
            raise HTTPException(status_code=413, detail=f"This file is too large (the limit is {cap // 1048576} MB).")
    if kind == "image":
        a, warnings = _wrap(lambda: studio.make_image_asset(ctx.db, tenant_id=ctx.tenant_id, data=bytes(raw), file_name=file_name, label=label, user_id=ctx.user.id))
    else:
        a, warnings = _wrap(lambda: studio.make_document_asset(ctx.db, tenant_id=ctx.tenant_id, data=bytes(raw), file_name=file_name, label=label, user_id=ctx.user.id))
    audit(ctx.db, action="marketing.asset_upload", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="marketing_asset", entity_id=a.id, meta={"kind": a.kind, "bytes": a.size_bytes}, ip=client_ip(request))
    ctx.db.commit()
    return _asset_out(a, warnings)


@router.get("/assets/{asset_id}/file")
def asset_file(asset_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    a = _asset(ctx, asset_id)
    ctx.db.refresh(a, ["data"])
    disp = "inline" if a.kind == "image" else "attachment"
    return Response(content=a.data, media_type=a.content_type, headers={"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff", "Content-Disposition": f'{disp}; filename="asset"',
                                                                        "Content-Security-Policy": "default-src 'none'; sandbox"})


@router.delete("/assets/{asset_id}")
def delete_asset(asset_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    a = _asset(ctx, asset_id)
    live = ctx.db.scalar(select(func.count()).select_from(ScheduledPost).where(ScheduledPost.asset_id == a.id, ScheduledPost.status.in_(("draft", "awaiting_approval", "approved", "scheduled", "publishing"))))
    if live:
        raise HTTPException(status_code=409, detail="This photo is attached to a post that hasn't been published yet. Remove it from the post first.")
    ctx.db.execute(ScheduledPost.__table__.update().where(ScheduledPost.asset_id == a.id).values(asset_id=None))
    ctx.db.delete(a)
    audit(ctx.db, action="marketing.asset_delete", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="marketing_asset", entity_id=asset_id, ip=client_ip(request))
    ctx.db.commit()
    return {"deleted": True}


# ------------------------------------------------------------------ campaigns
@router.get("/campaigns")
def list_campaigns(google_location_id: uuid.UUID | None = None, ctx: TenantContext = Depends(get_tenant_context)):
    q = (select(MarketingCampaign).join(GoogleLocation, GoogleLocation.id == MarketingCampaign.google_location_id)
         .where(MarketingCampaign.tenant_id == ctx.tenant_id, MarketingCampaign.status != "archived", ctx.scope(GoogleLocation.location_id)).order_by(MarketingCampaign.created_at.desc()).limit(100))
    if google_location_id:
        q = q.where(MarketingCampaign.google_location_id == google_location_id)
    rows = ctx.db.scalars(q).all()
    counts = _counts(ctx, [c.id for c in rows])
    return {"campaigns": [_campaign_out(c, counts[c.id]) for c in rows]}


@router.post("/campaigns", status_code=201)
def create_campaign(body: CampaignIn, request: Request, ctx: TenantContext = Depends(get_tenant_context)):
    """Plan and write a campaign. Everything comes back as drafts waiting for review; nothing is sent to Google."""
    ent.require_active(ctx.db, ctx.tenant_id)
    _need(ctx)
    gl = _gloc(ctx, body.google_location_id)
    if quota_exceeded(ctx.db, ctx.tenant_id, "post_draft"):
        raise HTTPException(status_code=402, detail="Your subscription is not active")
    if not hit(f"mkt-gen:{ctx.tenant_id}", 12, 3600):
        raise HTTPException(status_code=429, detail="You've generated several campaigns this hour. Try again a little later.")
    tz = ZoneInfo(ctx.tenant.timezone or "Asia/Kolkata")
    today = datetime.now(tz).date()
    start = body.start_date or today
    if start < today or (start - today).days > 60:
        raise HTTPException(status_code=422, detail="Choose a start date between today and the next 60 days.")
    ids = [str(i) for i in dict.fromkeys(body.asset_ids)]
    if ids:
        found = ctx.db.scalar(select(func.count()).select_from(MarketingAsset).where(MarketingAsset.tenant_id == ctx.tenant_id, MarketingAsset.id.in_(body.asset_ids)))
        if found != len(ids):
            raise HTTPException(status_code=422, detail="One of the chosen files was not found.")  # also covers another business's file ids: they simply do not exist for this one
    es, ee = body.event_start, body.event_end
    if es and es.tzinfo is None:
        es = es.replace(tzinfo=tz)
    if ee and ee.tzinfo is None:
        ee = ee.replace(tzinfo=tz)
    if body.objective == "events" and es and ee and ee <= es:
        raise HTTPException(status_code=422, detail="The event must end after it starts.")
    try:
        provider = metered(get_provider(), ctx.db, ctx.tenant_id, "campaign", actor_user_id=ctx.user.id)
    except AIUnavailable:
        raise HTTPException(status_code=503, detail="AI is not configured on this server. Setup required: add an AI provider key. You can still write posts yourself on the Posts page.")
    kb = kbs.context(ctx.db, ctx.tenant)
    intel = intelligence.build(ctx.db, ctx.tenant, kb, google_location_id=gl.id)
    title = (body.brief.strip().splitlines()[0])[:80]
    c = MarketingCampaign(tenant_id=ctx.tenant_id, google_location_id=gl.id, title=title, brief=body.brief.strip(), objective=body.objective, duration_days=body.duration_days, start_date=start,
                          language=body.language or (ctx.tenant.language if ctx.tenant.language in ("en", "hi", "hinglish") else "en"), status="generating", event_title=(body.event_title or "").strip() or None,
                          event_start=es, event_end=ee, asset_ids=ids, created_by=ctx.user.id)
    ctx.db.add(c)
    ctx.db.flush()
    import time as _t
    started = _t.monotonic()
    try:
        made = _wrap(lambda: studio.generate(ctx.db, provider, ctx.tenant, gl, c, kb, intel, user_id=ctx.user.id))
    except HTTPException:
        ctx.db.rollback()
        raise
    except AIUnavailable as exc:
        ctx.db.rollback()
        if getattr(exc, "scope", None):
            raise HTTPException(status_code=402, detail=str(exc))
        log_generation(ctx.db, tenant_id=ctx.tenant_id, kind="campaign", provider=provider.name, model=provider.model, language=None, input_chars=len(body.brief), output_chars=0, status="error",
                       started=started, location_id=gl.location_id, error=str(exc), usage=getattr(provider, "usage", None))
        ctx.db.commit()
        raise HTTPException(status_code=502, detail="The AI couldn't write a safe campaign just now" + (" (every draft broke a safety rule, so nothing is shown)" if exc.code == "rejected" else "") + ". Try again, or write a post yourself.")
    c.status = "ready"
    log_generation(ctx.db, tenant_id=ctx.tenant_id, kind="campaign", provider=provider.name, model=provider.model, language=c.language, input_chars=len(body.brief), output_chars=sum(len(p.summary) for p in made),
                   status="ok", started=started, location_id=gl.location_id, usage=getattr(provider, "usage", None))
    audit(ctx.db, action="marketing.campaign_create", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="marketing_campaign", entity_id=c.id,
          meta={"objective": c.objective, "days": c.duration_days, "posts": len(made)}, ip=client_ip(request))
    ctx.db.commit()
    return _detail(ctx, c, kb)


def _history(ctx: TenantContext, p: ScheduledPost) -> list[dict]:
    rows = ctx.db.scalars(select(AgentAction).where(AgentAction.tenant_id == ctx.tenant_id, AgentAction.subject_type == "post", AgentAction.subject_id == p.id).order_by(AgentAction.created_at)).all()
    return [{"at": a.executed_at or a.created_at, "status": a.status, "error": a.last_error, "verified": a.verified_at is not None} for a in rows]


def _detail(ctx: TenantContext, c: MarketingCampaign, kb: dict | None = None) -> dict:
    kb = kb or kbs.context(ctx.db, ctx.tenant)
    posts = ctx.db.scalars(select(ScheduledPost).where(ScheduledPost.campaign_id == c.id, ScheduledPost.tenant_id == ctx.tenant_id).order_by(func.coalesce(ScheduledPost.scheduled_for, ScheduledPost.suggested_for), ScheduledPost.created_at)).all()
    out = []
    for p in posts:
        d = _post_out(ctx, p, kb)
        d.update({"campaign_id": str(p.campaign_id), "asset_id": str(p.asset_id) if p.asset_id else None, "keywords": p.keywords or [], "suggested_for": p.suggested_for,
                  "history": _history(ctx, p) if p.status in ("published", "failed", "scheduled", "publishing") else []})
        out.append(d)
    return {**_campaign_out(c, _counts(ctx, [c.id])[c.id]), "posts": out, "timezone": ctx.tenant.timezone}


@router.get("/campaigns/{campaign_id}")
def get_campaign(campaign_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    c = _campaign(ctx, campaign_id)
    out = _detail(ctx, c)
    ctx.db.commit()
    return out


@router.post("/campaigns/{campaign_id}/archive")
def archive_campaign(campaign_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Hide a campaign and cancel its posts that have not gone out. Published posts stay on Google and in history."""
    c = _campaign(ctx, campaign_id)
    for p in ctx.db.scalars(select(ScheduledPost).where(ScheduledPost.campaign_id == c.id, ScheduledPost.tenant_id == ctx.tenant_id).with_for_update()).all():
        if p.status in ("draft", "awaiting_approval", "approved", "scheduled", "failed"):
            post_svc.move(p, "canceled")
    c.status = "archived"
    audit(ctx.db, action="marketing.campaign_archive", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="marketing_campaign", entity_id=c.id, ip=client_ip(request))
    ctx.db.commit()
    return {"archived": True}


# ------------------------------------------------------------------ one post inside a campaign
def _campaign_post(ctx: TenantContext, post_id: uuid.UUID, *, lock: bool = False) -> ScheduledPost:
    q = select(ScheduledPost).where(ScheduledPost.id == post_id, ScheduledPost.tenant_id == ctx.tenant_id)
    p = ctx.db.scalar(q.with_for_update() if lock else q)
    gl = ctx.db.get(GoogleLocation, p.google_location_id) if p else None
    if not p or not gl or not ctx.can_access_location(gl.location_id):
        raise HTTPException(status_code=404, detail="Post not found")
    return p


@router.post("/posts/{post_id}/regenerate")
def regenerate_post(post_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(get_tenant_context)):
    ent.require_active(ctx.db, ctx.tenant_id)
    _need(ctx)
    p = _campaign_post(ctx, post_id, lock=True)
    gl = ctx.db.get(GoogleLocation, p.google_location_id)
    if quota_exceeded(ctx.db, ctx.tenant_id, "post_draft"):
        raise HTTPException(status_code=402, detail="Your subscription is not active")
    if not hit(f"mkt-regen:{ctx.tenant_id}", 40, 3600):
        raise HTTPException(status_code=429, detail="Too many rewrites this hour. Try again a little later.")
    try:
        provider = metered(get_provider(), ctx.db, ctx.tenant_id, "campaign", actor_user_id=ctx.user.id)
    except AIUnavailable:
        raise HTTPException(status_code=503, detail="AI is not configured on this server. Setup required: add an AI provider key.")
    kb = kbs.context(ctx.db, ctx.tenant)
    intel = intelligence.build(ctx.db, ctx.tenant, kb, google_location_id=gl.id)
    sibs = [s for (s,) in ctx.db.execute(select(ScheduledPost.summary).where(ScheduledPost.tenant_id == ctx.tenant_id, ScheduledPost.campaign_id == p.campaign_id, ScheduledPost.id != p.id)).all()] if p.campaign_id else []
    try:
        _wrap(lambda: studio.regenerate(ctx.db, provider, ctx.tenant, gl, p, kb, intel, sibs))
    except AIUnavailable as exc:
        if getattr(exc, "scope", None):
            raise HTTPException(status_code=402, detail=str(exc))
        raise HTTPException(status_code=502, detail="The AI couldn't write a safe replacement just now. Try again, or edit the post yourself.")
    audit(ctx.db, action="marketing.post_regenerate", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="scheduled_post", entity_id=p.id, ip=client_ip(request))
    ctx.db.commit()
    return _post_out(ctx, p, kb)


@router.put("/posts/{post_id}/asset")
def set_post_asset(post_id: uuid.UUID, body: AssetPostIn, request: Request, ctx: TenantContext = Depends(get_tenant_context)):
    """Choose which library image goes with a post (or none). The image is served to Google from a public address only from this moment."""
    ent.require_active(ctx.db, ctx.tenant_id)
    _need(ctx)
    p = _campaign_post(ctx, post_id, lock=True)
    if p.status not in post_svc.EDITABLE:
        raise HTTPException(status_code=409, detail=f"A post that is {p.status.replace('_', ' ')} can't be changed. Cancel it or move it back to draft first.")
    if body.asset_id is None:
        p.asset_id = p.photo_url = None
    else:
        a = _asset(ctx, body.asset_id)
        p.photo_url = _wrap(lambda: studio.public_url(ctx.db, a))
        p.asset_id = a.id
    if p.status == "awaiting_approval":
        post_svc.move(p, "draft")  # approving covers the photo too: a change voids a pending approval request, like any edit
        post_svc.move(p, "awaiting_approval")
    audit(ctx.db, action="marketing.post_photo", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="scheduled_post", entity_id=p.id, meta={"asset": str(body.asset_id) if body.asset_id else None}, ip=client_ip(request))
    ctx.db.commit()
    d = _post_out(ctx, p, kbs.context(ctx.db, ctx.tenant))
    return {**d, "asset_id": str(p.asset_id) if p.asset_id else None}


@router.post("/posts/{post_id}/reschedule")
def reschedule_post(post_id: uuid.UUID, body: RescheduleIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Move an approved, scheduled post to another time, or publish it now (through the governed engine). Only a post that is waiting in the queue can move: one that is
    already being published, published or failed cannot (a failed one is retried instead)."""
    from app.api.v1 import posts as posts_api
    ent.require_active(ctx.db, ctx.tenant_id)
    _need(ctx)
    p = _campaign_post(ctx, post_id, lock=True)
    if p.status != "scheduled":
        raise HTTPException(status_code=409, detail=f"Only a scheduled post can be moved. This one is {p.status.replace('_', ' ')}.")
    when = body.scheduled_for
    if when is not None and when.tzinfo is None:
        when = when.replace(tzinfo=ZoneInfo(ctx.tenant.timezone or "Asia/Kolkata"))
    now = utcnow()
    if when is not None and when > now + timedelta(days=365):
        raise HTTPException(status_code=422, detail="Choose a time within the next year.")
    result = None
    if when is None or when <= now + timedelta(seconds=30):
        p.scheduled_for, p.next_attempt_at = now, None
        result = posts_api._publish(ctx, p)  # a person pressed Publish now: the same engine, policy, claim and read-back as any publish
    else:
        p.scheduled_for, p.next_attempt_at = when, None
    audit(ctx.db, action="marketing.post_reschedule", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="scheduled_post", entity_id=p.id,
          meta={"to": p.scheduled_for.isoformat() if p.scheduled_for else None, "now": result is not None}, ip=client_ip(request))
    ctx.db.commit()
    return {**_post_out(ctx, p, kbs.context(ctx.db, ctx.tenant)), "publish_result": result}
