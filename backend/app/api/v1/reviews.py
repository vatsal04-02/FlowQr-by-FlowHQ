import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select

from app.core.deps import TenantContext, get_tenant_context, require_role
from app.core.rate_limit import client_ip
from app.models import Location, ReplyDraft, ReplyLog, ReplyStatus, Review, Role
from app.models.base import utcnow
from app.schemas.reviews import ApproveIn, DraftBodyIn, DraftOut, LogOut, ReviewDetail, ReviewList, ReviewOut
from app.services import reviews as review_svc
from app.services.ai import AIUnavailable, get_provider
from app.services.ai.replies import draft_reply, reason_labels
from app.services.ai.safety import assess_review
from app.services.ai_usage import log_generation, quota_exceeded
from app.services.audit import audit

router = APIRouter(tags=["reviews"])
REPLY_STATES = {"none", "draft", "approved", "published", "failed"}


def _latest_draft_status_sq():
    return (
        select(ReplyDraft.status).where(ReplyDraft.review_id == Review.id, ReplyDraft.status != ReplyStatus.rejected)
        .order_by(ReplyDraft.created_at.desc()).limit(1).correlate(Review).scalar_subquery()
    )


def _draft_out(d: ReplyDraft) -> DraftOut:
    out = DraftOut.model_validate(d)
    out.flag_messages = reason_labels(d.flag_reasons or [])
    return out


def _review_out(ctx: TenantContext, r: Review, loc_names: dict) -> ReviewOut:
    drafts = [d for d in r.drafts if d.status != ReplyStatus.rejected]
    latest = drafts[-1] if drafts else None
    if r.google_reply_text is not None:
        state = "published"
    elif latest:
        state = latest.status.value
    else:
        state = "none"
    return ReviewOut(
        id=r.id, location_id=r.location_id, location_name=loc_names.get(r.location_id), rating=r.rating, text=r.text,
        reviewer_name=r.reviewer_name, review_created_at=r.review_created_at, review_updated_at=r.review_updated_at,
        update_count=r.update_count, google_reply_text=r.google_reply_text, google_reply_at=r.google_reply_at,
        reply_state=state, sensitive_reasons=assess_review(r.text, r.rating, ctx.tenant.category),
        latest_draft=_draft_out(latest) if latest else None,
    )


def _loc_names(ctx: TenantContext) -> dict:
    return {l.id: l.name for l in ctx.db.scalars(select(Location).where(Location.tenant_id == ctx.tenant_id))}


def _review_or_404(ctx: TenantContext, review_id: uuid.UUID) -> Review:
    r = ctx.db.scalar(select(Review).where(Review.id == review_id, Review.tenant_id == ctx.tenant_id))
    if not r:
        raise HTTPException(status_code=404, detail="Review not found")
    return r


def _draft_or_404(ctx: TenantContext, draft_id: uuid.UUID) -> ReplyDraft:
    d = ctx.db.scalar(select(ReplyDraft).where(ReplyDraft.id == draft_id, ReplyDraft.tenant_id == ctx.tenant_id))
    if not d:
        raise HTTPException(status_code=404, detail="Draft not found")
    return d


@router.get("/reviews", response_model=ReviewList)
def list_reviews(
    ctx: TenantContext = Depends(get_tenant_context),
    location_id: uuid.UUID | None = None,
    rating: int | None = Query(None, ge=1, le=5),
    reply_state: str | None = None,
    search: str | None = Query(None, max_length=100),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    q = select(Review).where(Review.tenant_id == ctx.tenant_id)
    if location_id:
        q = q.where(Review.location_id == location_id)
    if rating:
        q = q.where(Review.rating == rating)
    if search:
        q = q.where(Review.text.ilike(f"%{search}%") | Review.reviewer_name.ilike(f"%{search}%"))
    if reply_state:
        if reply_state not in REPLY_STATES:
            raise HTTPException(status_code=422, detail="Unknown reply_state")
        latest = _latest_draft_status_sq()
        if reply_state == "published":
            q = q.where(Review.google_reply_text.is_not(None))
        elif reply_state == "none":
            q = q.where(Review.google_reply_text.is_(None), latest.is_(None))
        else:
            q = q.where(Review.google_reply_text.is_(None), latest == ReplyStatus(reply_state))
    total = ctx.db.scalar(select(func.count()).select_from(q.subquery()))
    rows = ctx.db.scalars(q.order_by(Review.review_created_at.desc()).limit(limit).offset(offset)).unique().all()
    names = _loc_names(ctx)
    return ReviewList(total=total, items=[_review_out(ctx, r, names) for r in rows])


@router.get("/reviews/{review_id}", response_model=ReviewDetail)
def review_detail(review_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    r = _review_or_404(ctx, review_id)
    logs = ctx.db.scalars(select(ReplyLog).where(ReplyLog.review_id == r.id, ReplyLog.tenant_id == ctx.tenant_id).order_by(ReplyLog.created_at.desc())).all()
    return ReviewDetail(
        review=_review_out(ctx, r, _loc_names(ctx)),
        drafts=[_draft_out(d) for d in reversed(r.drafts)],
        logs=[LogOut.model_validate(l) for l in logs],
    )


@router.post("/reviews/{review_id}/drafts/generate", response_model=DraftOut, status_code=201)
def generate_draft(review_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(get_tenant_context)):
    r = _review_or_404(ctx, review_id)
    if quota_exceeded(ctx.db, ctx.tenant_id):
        raise HTTPException(status_code=402, detail="Monthly AI limit reached for your plan")
    started = time.monotonic()
    try:
        provider = get_provider()
    except AIUnavailable:
        raise HTTPException(status_code=503, detail="AI is not configured on this server. You can still write a reply manually.")
    names = _loc_names(ctx)
    try:
        body, lang, reasons = draft_reply(provider, r, ctx.tenant, names.get(r.location_id))
    except AIUnavailable as exc:
        log_generation(ctx.db, tenant_id=ctx.tenant_id, kind="reply_draft", provider=provider.name, model=provider.model,
                       language=None, input_chars=len(r.text or ""), output_chars=0, status="error", started=started,
                       location_id=r.location_id, error=str(exc))
        ctx.db.commit()
        raise HTTPException(status_code=502, detail="The AI couldn't draft a reply. Try again or write one manually.")
    d = ReplyDraft(
        tenant_id=ctx.tenant_id, review_id=r.id, body=body, language=lang, generated_by_ai=True, created_by=ctx.user.id,
        requires_human_handling=bool(reasons), flag_reasons=reasons, status=ReplyStatus.draft,
    )
    ctx.db.add(d)
    log_generation(ctx.db, tenant_id=ctx.tenant_id, kind="reply_draft", provider=provider.name, model=provider.model,
                   language=lang, input_chars=len(r.text or ""), output_chars=len(body), status="ok", started=started,
                   location_id=r.location_id)
    ctx.db.commit()
    ctx.db.refresh(d)
    return _draft_out(d)


@router.post("/reviews/{review_id}/drafts", response_model=DraftOut, status_code=201)
def create_manual_draft(review_id: uuid.UUID, body: DraftBodyIn, ctx: TenantContext = Depends(get_tenant_context)):
    r = _review_or_404(ctx, review_id)
    reasons = assess_review(r.text, r.rating, ctx.tenant.category)
    d = ReplyDraft(tenant_id=ctx.tenant_id, review_id=r.id, body=body.body.strip(), generated_by_ai=False,
                   created_by=ctx.user.id, language=ctx.tenant.language, requires_human_handling=bool(reasons), flag_reasons=reasons)
    ctx.db.add(d)
    ctx.db.commit()
    ctx.db.refresh(d)
    return _draft_out(d)


@router.patch("/reply-drafts/{draft_id}", response_model=DraftOut)
def edit_draft(draft_id: uuid.UUID, body: DraftBodyIn, ctx: TenantContext = Depends(get_tenant_context)):
    d = _draft_or_404(ctx, draft_id)
    if d.status in (ReplyStatus.published, ReplyStatus.rejected):
        raise HTTPException(status_code=409, detail="This reply can no longer be edited")
    d.body = body.body.strip()
    # Any edit voids a previous approval: the approved text must be exactly what gets published.
    d.status, d.approved_by, d.approved_at, d.failure_reason = ReplyStatus.draft, None, None, None
    ctx.db.commit()
    return _draft_out(d)


@router.delete("/reply-drafts/{draft_id}", status_code=204)
def reject_draft(draft_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    d = _draft_or_404(ctx, draft_id)
    if d.status == ReplyStatus.published:
        raise HTTPException(status_code=409, detail="Already published")
    d.status = ReplyStatus.rejected
    ctx.db.commit()


@router.post("/reply-drafts/{draft_id}/approve", response_model=DraftOut)
def approve_draft(draft_id: uuid.UUID, body: ApproveIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    d = _draft_or_404(ctx, draft_id)
    if d.status != ReplyStatus.draft:
        raise HTTPException(status_code=409, detail=f"A {d.status.value} reply can't be approved")
    if d.requires_human_handling and not body.acknowledge_flags:
        raise HTTPException(status_code=409, detail={"code": "flags_need_acknowledgement",
                            "message": "This review was flagged for human handling. Confirm you've reviewed it personally.",
                            "reasons": reason_labels(d.flag_reasons or [])})
    d.status, d.approved_by, d.approved_at = ReplyStatus.approved, ctx.user.id, utcnow()
    audit(ctx.db, action="reply.approve", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="reply_draft",
          entity_id=d.id, ip=client_ip(request))
    ctx.db.commit()
    return _draft_out(d)


@router.post("/reply-drafts/{draft_id}/publish", response_model=DraftOut)
def publish_draft(draft_id: uuid.UUID, request: Request, replace_existing: bool = False,
                  ctx: TenantContext = Depends(require_role(Role.admin))):
    d = _draft_or_404(ctx, draft_id)
    if d.status not in (ReplyStatus.approved, ReplyStatus.failed) or not d.approved_by:
        raise HTTPException(status_code=409, detail="Approve the reply before publishing")
    review = ctx.db.get(Review, d.review_id)
    if review.google_reply_text is not None and not replace_existing:
        raise HTTPException(status_code=409, detail={"code": "reply_exists", "message": "Google already shows a reply to this review. Publishing will replace it."})
    audit(ctx.db, action="reply.publish_attempt", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="reply_draft",
          entity_id=d.id, ip=client_ip(request))
    d = review_svc.publish_draft(ctx.db, d, by_user=ctx.user)
    return _draft_out(d)
