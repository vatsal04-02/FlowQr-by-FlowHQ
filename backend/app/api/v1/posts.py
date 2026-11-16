"""Google Posts: drafts, approval, our own scheduler, retries and history.

Google does not schedule posts, so an approved post waits here and a Celery job publishes it when due. Nothing reaches Google without a
person approving that exact text; a post is `published` only after Google returned it.
"""
import logging
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
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
from app.services.agent import content_exec
from app.services.agent import knowledge as kbs
from app.services.agent import posts as svc
from app.services.agent.safety import check_text
from app.services.ai import AIUnavailable, get_provider
from app.services.ai import intelligence, outcomes
from app.services.ai_usage import log_generation, metered, quota_exceeded
from app.services.audit import audit

log = logging.getLogger("flowqr.posts.api")
router = APIRouter(prefix="/posts", tags=["posts"])


class PostCreateIn(PostIn):
    google_location_id: uuid.UUID
    topic_type: Literal["STANDARD", "OFFER", "EVENT"] = "STANDARD"
    event_title: str | None = Field(default=None, max_length=58)
    event_start: datetime | None = None
    event_end: datetime | None = None
    offer_coupon: str | None = Field(default=None, max_length=58)
    offer_url: str | None = Field(default=None, max_length=500)
    offer_terms: str | None = Field(default=None, max_length=1500)


class TopicFields(BaseModel):
    """Post type (Google LocalPostTopicType) and, for offers and events, Google's required title and schedule. Times are read in the
    business's time zone when they carry no offset."""
    topic_type: Literal["STANDARD", "OFFER", "EVENT"] | None = None
    event_title: str | None = Field(default=None, max_length=58)
    event_start: datetime | None = None
    event_end: datetime | None = None
    offer_coupon: str | None = Field(default=None, max_length=58)
    offer_url: str | None = Field(default=None, max_length=500)
    offer_terms: str | None = Field(default=None, max_length=1500)


class PostEditIn(TopicFields):
    summary: str | None = Field(default=None, min_length=10, max_length=1500)
    cta_type: str | None = None
    cta_url: str | None = Field(default=None, max_length=500)
    photo_url: str | None = Field(default=None, max_length=500)


class AiDraftIn(BaseModel):
    google_location_id: uuid.UUID
    topic: str | None = Field(default=None, max_length=200)
    # update = a normal post; offer = only from a verified offer in the knowledge base; event = from the title/dates the owner gives
    kind: Literal["update", "offer", "event"] = "update"
    event_title: str | None = Field(default=None, max_length=58)
    event_start: datetime | None = None
    event_end: datetime | None = None


class ApproveIn(BaseModel):
    scheduled_for: datetime | None = None  # a time in the future; naive values are read in the business's time zone. Omit to publish now.


def _local(ctx: TenantContext, d: datetime | None) -> datetime | None:
    """A time without an offset means the business's own wall-clock time."""
    if d is None or d.tzinfo is not None:
        return d
    return d.replace(tzinfo=ZoneInfo(ctx.tenant.timezone or "Asia/Kolkata"))


def _apply_topic(ctx: TenantContext, p: ScheduledPost, data: dict) -> None:
    for k in ("topic_type", "event_title", "event_start", "event_end", "offer_coupon", "offer_url", "offer_terms"):
        if k in data:
            v = data[k]
            setattr(p, k, _local(ctx, v) if k in ("event_start", "event_end") else (v.strip() or None) if isinstance(v, str) else v)
    if p.topic_type == "STANDARD":  # an update has no schedule or offer: clear leftovers so Google never receives them
        p.event_title = p.event_start = p.event_end = p.offer_coupon = p.offer_url = p.offer_terms = None
    elif p.topic_type == "EVENT":
        p.offer_coupon = p.offer_url = p.offer_terms = None


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
            "approved_at": p.approved_at, "created_at": p.created_at, "violations": svc.validate_content(p, kb) if p.status in ("draft", "awaiting_approval", "failed", "approved") else [],
            "topic_type": p.topic_type or "STANDARD", "event_title": p.event_title, "event_start": p.event_start, "event_end": p.event_end, "offer_coupon": p.offer_coupon,
            "offer_url": p.offer_url, "offer_terms": p.offer_terms, "visual_hint": p.visual_hint, "topic_problems": svc.topic_problems(p)}


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
                      photo_url=body.photo_url, status="draft", created_by=ctx.user.id, topic_type=body.topic_type)
    _apply_topic(ctx, p, body.model_dump(include={"event_title", "event_start", "event_end", "offer_coupon", "offer_url", "offer_terms"}))
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
    if quota_exceeded(ctx.db, ctx.tenant_id, "post_draft"):
        raise HTTPException(status_code=402, detail="Your subscription is not active")
    try:
        provider = metered(get_provider(), ctx.db, ctx.tenant_id, "post_draft", actor_user_id=ctx.user.id)
    except AIUnavailable:
        raise HTTPException(status_code=503, detail="AI is not configured on this server. Setup required: add an AI provider key. You can still write a post yourself.")
    kb = kbs.context(ctx.db, ctx.tenant)
    topic = body.topic
    if body.kind == "offer":
        if not kb["offers"]:
            raise HTTPException(status_code=422, detail="Add a verified offer to your Business brain first. The AI never invents offers or discounts.")
        topic = topic or "present one of the verified offers exactly as written, with its conditions"
    elif body.kind == "event":
        if not (body.event_title and body.event_start and body.event_end):
            raise HTTPException(status_code=422, detail="Give the event a title, a start and an end. The AI writes the text; it doesn't invent events.")
        topic = f"announce this event: {body.event_title}, from {_local(ctx, body.event_start):%d %b %Y %H:%M} to {_local(ctx, body.event_end):%d %b %Y %H:%M}. " + (topic or "")
    recent = [x.summary for x in ctx.db.scalars(select(ScheduledPost).where(ScheduledPost.tenant_id == ctx.tenant_id).order_by(ScheduledPost.created_at.desc()).limit(5))]
    import time as _t
    started = _t.monotonic()
    try:
        from app.models import GbpSnapshot
        from app.services.agent.optimizer import search_terms_line
        snap = ctx.db.scalar(select(GbpSnapshot).where(GbpSnapshot.google_location_id == gl.id))
        intel = intelligence.build(ctx.db, ctx.tenant, kb, google_location_id=gl.id)
        text, qa, _ptype = svc.draft_post_scored(provider, ctx.tenant, kb, topic=topic, avoid=recent, terms=search_terms_line(snap), intel=intel)
    except AIUnavailable as exc:
        if getattr(exc, "scope", None):  # a spending budget stopped it (services/ai_usage.BudgetExceeded): say so, don't call it a failure
            raise HTTPException(status_code=402, detail=str(exc))
        log_generation(ctx.db, tenant_id=ctx.tenant_id, kind="post_draft", provider=provider.name, model=provider.model, language=None, input_chars=0, output_chars=0, status="error",
                       started=started, location_id=gl.location_id, error=str(exc), usage=getattr(provider, "usage", None))
        ctx.db.commit()
        raise HTTPException(status_code=502, detail="The AI couldn't write a safe post. " + ("It broke a safety rule twice, so nothing is shown. " if exc.code == "rejected" else "") + "Try again or write one yourself.")
    log_generation(ctx.db, tenant_id=ctx.tenant_id, kind="post_draft", provider=provider.name, model=provider.model, language=ctx.tenant.language, input_chars=len(body.topic or ""),
                   output_chars=len(text), status="ok", started=started, location_id=gl.location_id, usage=getattr(provider, "usage", None))
    p = ScheduledPost(tenant_id=ctx.tenant_id, google_location_id=gl.id, summary=text, language=ctx.tenant.language if ctx.tenant.language in ("en", "hi") else "en",
                      status="draft", generated_by_ai=True, created_by=ctx.user.id, topic_type={"update": "STANDARD", "offer": "OFFER", "event": "EVENT"}[body.kind])
    if body.kind == "event":
        _apply_topic(ctx, p, {"event_title": body.event_title, "event_start": body.event_start, "event_end": body.event_end})
    p.visual_hint = svc.visual_hint(provider, text, ctx.tenant.category)
    ctx.db.add(p)
    ctx.db.flush()
    outcomes.record_generated(ctx.db, ctx.tenant_id, "post", p.id, text, model=provider.model, language=ctx.tenant.language, score=qa.score if qa else None)
    svc.move(p, "awaiting_approval")
    audit(ctx.db, action="post.ai_draft", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="scheduled_post", entity_id=p.id, ip=client_ip(request))
    ctx.db.commit()
    return _out(ctx, p, kb)


class IdeasIn(BaseModel):
    google_location_id: uuid.UUID
    count: int = Field(default=3, ge=2, le=5)
    language: str | None = Field(default=None, pattern="^(en|hi|hinglish)$")


@router.post("/ideas")
def post_ideas(body: IdeasIn, ctx: TenantContext = Depends(get_tenant_context)):
    """Several genuinely different post concepts (type, full text, a real photo to take, the business purpose), each already checked against the knowledge
    base and against what was posted recently. Nothing is saved: pick one, edit it, and create it as a draft."""
    ent.require_active(ctx.db, ctx.tenant_id)
    _need(ctx)
    gl = _gloc(ctx, body.google_location_id)
    if quota_exceeded(ctx.db, ctx.tenant_id, "post_ideas"):
        raise HTTPException(status_code=402, detail="Your subscription is not active")
    try:
        provider = metered(get_provider(), ctx.db, ctx.tenant_id, "post_ideas", actor_user_id=ctx.user.id)
    except AIUnavailable:
        raise HTTPException(status_code=503, detail="AI is not configured on this server. Setup required: add an AI provider key.")
    kb = kbs.context(ctx.db, ctx.tenant)
    intel = intelligence.build(ctx.db, ctx.tenant, kb, google_location_id=gl.id)
    import time as _t
    started = _t.monotonic()
    from app.models import GbpSnapshot
    from app.services.agent.optimizer import search_terms_line
    snap = ctx.db.scalar(select(GbpSnapshot).where(GbpSnapshot.google_location_id == gl.id))
    try:
        ideas = svc.post_ideas(provider, ctx.tenant, kb, intel, n=body.count, language=body.language, terms=search_terms_line(snap))
    except AIUnavailable as exc:
        if getattr(exc, "scope", None):  # a spending budget stopped it (services/ai_usage.BudgetExceeded): say so, don't call it a failure
            raise HTTPException(status_code=402, detail=str(exc))
        log_generation(ctx.db, tenant_id=ctx.tenant_id, kind="post_ideas", provider=provider.name, model=provider.model, language=None, input_chars=0, output_chars=0, status="error",
                       started=started, location_id=gl.location_id, error=str(exc), usage=getattr(provider, "usage", None))
        ctx.db.commit()
        raise HTTPException(status_code=502, detail="The AI couldn't come up with safe ideas just now. Try again, or write a post yourself.")
    log_generation(ctx.db, tenant_id=ctx.tenant_id, kind="post_ideas", provider=provider.name, model=provider.model, language=ctx.tenant.language, input_chars=0,
                   output_chars=sum(len(i["text"]) for i in ideas), status="ok", started=started, location_id=gl.location_id, usage=getattr(provider, "usage", None))
    ctx.db.commit()
    return {"ideas": ideas, "missing": intel["missing"][:3], "note": "Each idea uses only facts from your Business brain. Edit anything before you approve; nothing is published until you do."}


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
    topic_keys = {"topic_type", "event_title", "event_start", "event_end", "offer_coupon", "offer_url", "offer_terms"}
    for k, v in data.items():
        if k not in topic_keys:
            setattr(p, k, v.strip() if isinstance(v, str) else v)
    _apply_topic(ctx, p, {k: v for k, v in data.items() if k in topic_keys})
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


def _publish(ctx: TenantContext, p: ScheduledPost) -> str:
    """The one way a post reaches Google: through the governed engine (policy, emergency stop, claim, read-back, history), which calls the existing publisher."""
    out = content_exec.run(ctx.db, "post", p, role=ctx.role)
    return {"done": "published"}.get(out["outcome"], out["outcome"])


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
    outcomes.record_decision(ctx.db, "post", p.id, "approved", final_text=p.summary)
    audit(ctx.db, action="post.approve", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="scheduled_post", entity_id=p.id,
          meta={"scheduled_for": p.scheduled_for.isoformat() if p.scheduled_for else None, "chars": len(p.summary)}, ip=client_ip(request))
    result = None
    if when is None or p.scheduled_for <= utcnow():
        result = _publish(ctx, p)  # now: the owner sees Google's real answer
        audit(ctx.db, action=f"post.publish_{result}", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="scheduled_post", entity_id=p.id,
              meta={"status": p.status, "reason": p.failure_reason}, ip=client_ip(request))
    ctx.db.commit()
    return {**_out(ctx, p, kb), "publish_result": result}


@router.post("/{post_id}/cancel")
def cancel(post_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    p = _post(ctx, post_id, lock=True)
    _wrap(lambda: svc.move(p, "canceled"))
    outcomes.record_decision(ctx.db, "post", p.id, "rejected", reason="canceled")
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
    result = _publish(ctx, p)
    audit(ctx.db, action=f"post.retry_{result}", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="scheduled_post", entity_id=p.id,
          meta={"status": p.status, "reason": p.failure_reason}, ip=client_ip(request))
    ctx.db.commit()
    return {**_out(ctx, p), "publish_result": result}
