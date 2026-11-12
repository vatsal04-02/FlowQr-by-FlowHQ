"""Google Posts: drafts, approval, our own scheduler, retries and history.

Google does not schedule posts, so an approved post waits here and a Celery job publishes it when due. Nothing reaches Google without a
person approving that exact text; a post is `published` only after Google returned it.
"""
import logging
import uuid
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.deps import TenantContext, get_tenant_context, require_role
from app.core.rate_limit import client_ip
from app.models import GoogleConnection, GoogleConnectionStatus, GoogleLocation, Role, ScheduledPost
from app.models.base import utcnow
from app.schemas.gbp import PostIn
from app.services import entitlements as ent
from app.services.agent import knowledge as kbs
from app.services.agent import posts as svc
from app.services.agent.safety import check_text
from app.services.ai import AIUnavailable, get_provider
from app.services.ai_usage import log_generation, quota_exceeded
from app.services.audit import audit

log = logging.getLogger("flowqr.posts.api")
router = APIRouter(prefix="/posts", tags=["posts"])


class PostCreateIn(PostIn):
    google_location_id: uuid.UUID


class PostEditIn(BaseModel):
    summary: str | None = Field(default=None, min_length=10, max_length=1500)
    cta_type: str | None = None
    cta_url: str | None = Field(default=None, max_length=500)
    photo_url: str | None = Field(default=None, max_length=500)


class AiDraftIn(BaseModel):
    google_location_id: uuid.UUID
    topic: str | None = Field(default=None, max_length=200)


class ApproveIn(BaseModel):
    scheduled_for: datetime | None = None  # a time in the future; naive values are read in the business's time zone. Omit to publish now.


def _gloc(ctx: TenantContext, gid: uuid.UUID) -> GoogleLocation:
    gl = ctx.db.scalar(select(GoogleLocation).where(GoogleLocation.id == gid, GoogleLocation.tenant_id == ctx.tenant_id))
    if not gl or not gl.selected or not ctx.can_access_location(gl.location_id):
        raise HTTPException(status_code=404, detail="Google location not found")
    return gl


def _post(ctx: TenantContext, pid: uuid.UUID, *, lock: bool = False) -> ScheduledPost:
    q = select(ScheduledPost).where(ScheduledPost.id == pid, ScheduledPost.tenant_id == ctx.tenant_id)
    p = ctx.db.scalar(q.with_for_update() if lock else q)
    gl = ctx.db.get(GoogleLocation, p.google_location_id) if p else None
    if not p or not gl or not ctx.can_access_location(gl.location_id):
        raise HTTPException(status_code=404, detail="Post not found")
    return p


def _out(ctx: TenantContext, p: ScheduledPost, kb: dict | None = None) -> dict:
    kb = kb or kbs.context(ctx.db, ctx.tenant)
    gl = ctx.db.get(GoogleLocation, p.google_location_id)
    return {"id": str(p.id), "google_location_id": str(p.google_location_id), "location_title": gl.title if gl else None, "summary": p.summary, "language": p.language,
            "cta_type": p.cta_type, "cta_url": p.cta_url, "photo_url": p.photo_url, "status": p.status, "scheduled_for": p.scheduled_for, "next_attempt_at": p.next_attempt_at,
            "published_at": p.published_at, "google_post_name": p.google_post_name, "attempts": p.attempts, "failure_reason": p.failure_reason, "generated_by_ai": p.generated_by_ai,
            "approved_at": p.approved_at, "created_at": p.created_at, "violations": svc.validate_content(p, kb) if p.status in ("draft", "awaiting_approval", "failed", "approved") else []}


def _wrap(fn):
    try:
        return fn()
    except svc.PostError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


def _need(ctx: TenantContext) -> None:
    ent.require_feature(ctx.db, ctx.tenant_id, "gbp_posts")


@router.get("")
def list_posts(status: str | None = None, google_location_id: uuid.UUID | None = None, limit: int = Query(100, ge=1, le=300), ctx: TenantContext = Depends(get_tenant_context)):
    q = (select(ScheduledPost).join(GoogleLocation, GoogleLocation.id == ScheduledPost.google_location_id)
         .where(ScheduledPost.tenant_id == ctx.tenant_id, ctx.scope(GoogleLocation.location_id)).order_by(ScheduledPost.created_at.desc()).limit(limit))
    if status:
        q = q.where(ScheduledPost.status == status)
    if google_location_id:
        q = q.where(ScheduledPost.google_location_id == google_location_id)
    kb = kbs.context(ctx.db, ctx.tenant)
    rows = ctx.db.scalars(q).all()
    ctx.db.commit()
    return {"posts": [_out(ctx, p, kb) for p in rows], "timezone": ctx.tenant.timezone}


@router.get("/calendar")
def calendar(start: date = Query(alias="from"), end: date = Query(alias="to"), ctx: TenantContext = Depends(get_tenant_context)):
    """Posts by day: scheduled for that day, or published on it (in the business's time zone)."""
    if start > end or (end - start).days > 93:
        raise HTTPException(status_code=422, detail="Choose a range of up to 93 days.")
    tz = ZoneInfo(ctx.tenant.timezone or "Asia/Kolkata")
    lo, hi = datetime.combine(start, time.min, tzinfo=tz).astimezone(timezone.utc), datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc)
    when = func.coalesce(ScheduledPost.published_at, ScheduledPost.scheduled_for)
    rows = ctx.db.scalars(select(ScheduledPost).join(GoogleLocation, GoogleLocation.id == ScheduledPost.google_location_id).where(
        ScheduledPost.tenant_id == ctx.tenant_id, ScheduledPost.status.in_(("scheduled", "publishing", "published", "failed", "approved")), when >= lo, when < hi,
        ctx.scope(GoogleLocation.location_id)).order_by(when)).all()
    days: dict[str, list] = {}
    for p in rows:
        d = (p.published_at or p.scheduled_for).astimezone(tz).date().isoformat()
        days.setdefault(d, []).append({"id": str(p.id), "summary": p.summary[:120], "status": p.status, "at": p.published_at or p.scheduled_for})
    return {"from": start.isoformat(), "to": end.isoformat(), "timezone": ctx.tenant.timezone, "days": days}


@router.post("", status_code=201)
def create_post(body: PostCreateIn, request: Request, ctx: TenantContext = Depends(get_tenant_context)):
    ent.require_active(ctx.db, ctx.tenant_id)
    _need(ctx)
    gl = _gloc(ctx, body.google_location_id)
    p = ScheduledPost(tenant_id=ctx.tenant_id, google_location_id=gl.id, summary=body.summary.strip(), language=body.language, cta_type=body.cta_type, cta_url=body.cta_url,
                      photo_url=body.photo_url, status="draft", created_by=ctx.user.id)
    ctx.db.add(p)
    ctx.db.flush()
    audit(ctx.db, action="post.draft_create", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="scheduled_post", entity_id=p.id, ip=client_ip(request))
    ctx.db.commit()
    return _out(ctx, p)


@router.post("/ai-draft", status_code=201)
def ai_draft(body: AiDraftIn, request: Request, ctx: TenantContext = Depends(get_tenant_context)):
    """An AI post written from the knowledge base and checked against its rules. It waits for approval; nothing is sent to Google."""
    ent.require_active(ctx.db, ctx.tenant_id)
    _need(ctx)
    gl = _gloc(ctx, body.google_location_id)
    if quota_exceeded(ctx.db, ctx.tenant_id):
        raise HTTPException(status_code=402, detail="Monthly AI limit reached for your plan")
    try:
        provider = get_provider()
    except AIUnavailable:
        raise HTTPException(status_code=503, detail="AI is not configured on this server. Setup required: add an AI provider key. You can still write a post yourself.")
    kb = kbs.context(ctx.db, ctx.tenant)
    recent = [x.summary for x in ctx.db.scalars(select(ScheduledPost).where(ScheduledPost.tenant_id == ctx.tenant_id).order_by(ScheduledPost.created_at.desc()).limit(5))]
    import time as _t
    started = _t.monotonic()
    try:
        text, _ = svc.draft_post(provider, ctx.tenant, kb, topic=body.topic, avoid=recent)
    except AIUnavailable as exc:
        log_generation(ctx.db, tenant_id=ctx.tenant_id, kind="post_draft", provider=provider.name, model=provider.model, language=None, input_chars=0, output_chars=0, status="error",
                       started=started, location_id=gl.location_id, error=str(exc))
        ctx.db.commit()
        raise HTTPException(status_code=502, detail="The AI couldn't write a safe post. " + ("It broke a safety rule twice, so nothing is shown. " if exc.code == "rejected" else "") + "Try again or write one yourself.")
    log_generation(ctx.db, tenant_id=ctx.tenant_id, kind="post_draft", provider=provider.name, model=provider.model, language=ctx.tenant.language, input_chars=len(body.topic or ""),
                   output_chars=len(text), status="ok", started=started, location_id=gl.location_id)
    p = ScheduledPost(tenant_id=ctx.tenant_id, google_location_id=gl.id, summary=text, language=ctx.tenant.language if ctx.tenant.language in ("en", "hi") else "en",
                      status="draft", generated_by_ai=True, created_by=ctx.user.id)
    ctx.db.add(p)
    ctx.db.flush()
    svc.move(p, "awaiting_approval")
    audit(ctx.db, action="post.ai_draft", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="scheduled_post", entity_id=p.id, ip=client_ip(request))
    ctx.db.commit()
    return _out(ctx, p, kb)


@router.patch("/{post_id}")
def edit_post(post_id: uuid.UUID, body: PostEditIn, ctx: TenantContext = Depends(get_tenant_context)):
    p = _post(ctx, post_id)
    if p.status not in svc.EDITABLE:
        raise HTTPException(status_code=409, detail=f"A post that is {p.status.replace('_', ' ')} can't be edited. Cancel or move it back to draft first.")
    data = body.model_dump(exclude_unset=True)
    if data.get("cta_type") and data["cta_type"] not in {"LEARN_MORE", "BOOK", "ORDER", "SHOP", "SIGN_UP", "CALL"}:
        raise HTTPException(status_code=422, detail="Unsupported button")
    if data.get("cta_type") and data["cta_type"] != "CALL" and not (data.get("cta_url") or p.cta_url or "").startswith("https://"):
        raise HTTPException(status_code=422, detail="This button needs an https:// link")
    for k, v in data.items():
        setattr(p, k, v.strip() if isinstance(v, str) else v)
    if p.status == "awaiting_approval":
        svc.move(p, "draft")  # any edit voids a pending approval request: the approved text must be exactly what is published
    ctx.db.commit()
    return _out(ctx, p)


@router.post("/{post_id}/submit")
def submit(post_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    p = _post(ctx, post_id)
    _wrap(lambda: svc.move(p, "awaiting_approval"))
    ctx.db.commit()
    return _out(ctx, p)


@router.post("/{post_id}/reject")
def reject(post_id: uuid.UUID, ctx: TenantContext = Depends(require_role(Role.admin))):
    p = _post(ctx, post_id)
    _wrap(lambda: svc.move(p, "draft"))
    ctx.db.commit()
    return _out(ctx, p)


@router.post("/{post_id}/approve")
def approve(post_id: uuid.UUID, body: ApproveIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Approve exactly this text. With no time it is published right away (and you see Google's answer); with a time it waits for it."""
    ent.require_active(ctx.db, ctx.tenant_id)
    _need(ctx)
    p = _post(ctx, post_id, lock=True)
    kb = kbs.context(ctx.db, ctx.tenant)
    bad = svc.validate_content(p, kb)
    if bad:
        raise HTTPException(status_code=422, detail={"code": "safety_violation", "violations": bad, "message": "This text breaks a rule from your knowledge base. Edit it, then approve."})
    when = body.scheduled_for
    if when is not None and when.tzinfo is None:
        when = when.replace(tzinfo=ZoneInfo(ctx.tenant.timezone or "Asia/Kolkata"))
    if when is not None and when > utcnow() + timedelta(days=365):
        raise HTTPException(status_code=422, detail="Choose a time within the next year.")
    _wrap(lambda: svc.approve(p, user_id=ctx.user.id, when=when))
    audit(ctx.db, action="post.approve", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="scheduled_post", entity_id=p.id,
          meta={"scheduled_for": p.scheduled_for.isoformat() if p.scheduled_for else None, "chars": len(p.summary)}, ip=client_ip(request))
    result = None
    if when is None or p.scheduled_for <= utcnow():
        result = svc.publish(ctx.db, p)  # now: the owner sees Google's real answer
        audit(ctx.db, action=f"post.publish_{result}", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="scheduled_post", entity_id=p.id,
              meta={"status": p.status, "reason": p.failure_reason}, ip=client_ip(request))
    ctx.db.commit()
    return {**_out(ctx, p, kb), "publish_result": result}


@router.post("/{post_id}/cancel")
def cancel(post_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    p = _post(ctx, post_id, lock=True)
    _wrap(lambda: svc.move(p, "canceled"))
    audit(ctx.db, action="post.cancel", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="scheduled_post", entity_id=p.id, ip=client_ip(request))
    ctx.db.commit()
    return _out(ctx, p)


@router.post("/{post_id}/retry")
def retry(post_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    ent.require_active(ctx.db, ctx.tenant_id)
    p = _post(ctx, post_id, lock=True)
    bad = svc.validate_content(p, kbs.context(ctx.db, ctx.tenant))
    if bad:
        raise HTTPException(status_code=422, detail={"code": "safety_violation", "violations": bad, "message": "Edit this post first: it breaks a rule from your knowledge base."})
    _wrap(lambda: svc.retry(p))
    result = svc.publish(ctx.db, p)
    audit(ctx.db, action=f"post.retry_{result}", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="scheduled_post", entity_id=p.id,
          meta={"status": p.status, "reason": p.failure_reason}, ip=client_ip(request))
    ctx.db.commit()
    return {**_out(ctx, p), "publish_result": result}
