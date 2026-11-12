"""AI Growth Agent: knowledge base, business health, daily plan, approvals, activity, automation settings.

Reads work on any plan (your data is yours); anything that writes, drafts with AI or touches Google needs an active subscription and
the matching plan feature, and everything that reaches Google needs an owner/admin to approve it.
"""
import logging
import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import desc, func, select

from app.core.deps import TenantContext, get_tenant_context, require_role
from app.core.rate_limit import client_ip, hit
from app.models import (
    AgentRun, AgentSettings, AgentTask, AgentTaskEvent, GbpSnapshot, GoogleConnection, GoogleConnectionStatus, GoogleLocation, ReplyDraft, ReplyStatus, Review,
    Role, ScheduledPost,
)
from app.models.base import utcnow
from app.schemas.review_growth import ContextIn
from app.services import entitlements as ent
from app.services.agent import health as health_svc
from app.services.agent import knowledge as kbs
from app.services.agent import plan as plan_svc
from app.services.agent import posts as posts_svc
from app.services.agent import snapshots as snap_svc
from app.services.agent.safety import HEALTH_PROHIBITED_DEFAULTS, check_text, is_health
from app.services.ai import AIUnavailable, get_provider
from app.services.ai_usage import month_start, usage_this_month
from app.services.audit import audit

log = logging.getLogger("flowqr.agent.api")
router = APIRouter(prefix="/agent", tags=["agent"])
MAX_ITEMS = 40


# ------------------------------------------------------------------ knowledge base
class Offer(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    price_inr: int | None = Field(default=None, ge=0, le=10_000_000)
    details: str | None = Field(default=None, max_length=200)
    valid_until: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")


class Faq(BaseModel):
    q: str = Field(min_length=3, max_length=200)
    a: str = Field(min_length=3, max_length=600)


class KnowledgeIn(BaseModel):
    description: str | None = Field(default=None, max_length=600)
    services: list[str] = Field(default_factory=list, max_length=30)
    offers: list[Offer] = Field(default_factory=list, max_length=MAX_ITEMS)
    hours: str | None = Field(default=None, max_length=500)
    faqs: list[Faq] = Field(default_factory=list, max_length=MAX_ITEMS)
    brand_voice: str | None = Field(default=None, max_length=300)
    approved_claims: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)
    prohibited_claims: list[str] = Field(default_factory=list, max_length=MAX_ITEMS)

    @field_validator("approved_claims", "prohibited_claims")
    @classmethod
    def _phrases(cls, v):
        out = []
        for s in v:
            s = " ".join(str(s).split())
            if len(s) > 120:
                raise ValueError("Each phrase can be up to 120 characters.")
            if s and s.lower() not in {x.lower() for x in out}:
                out.append(s)
        return out


def _knowledge_out(ctx: TenantContext) -> dict:
    kb = kbs.context(ctx.db, ctx.tenant)
    return {**kb, "completeness": kbs.completeness(kb), "health_defaults": HEALTH_PROHIBITED_DEFAULTS if kb["safety_profile"] == "health" else [],
            "grounding_preview": kbs.render(kb)}


@router.get("/knowledge")
def get_knowledge(ctx: TenantContext = Depends(get_tenant_context)):
    out = _knowledge_out(ctx)
    ctx.db.commit()  # persists the seeded row on first read
    return out


@router.put("/knowledge")
def put_knowledge(body: KnowledgeIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    try:  # description and services use the same plain-text rules as the review assistant (no claims, prices or links in them)
        base = ContextIn.model_validate({**(ctx.tenant.review_context or {}), "description": body.description or "", "services": body.services})
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="; ".join(e["msg"].replace("Value error, ", "") for e in exc.errors()))
    rc = dict(ctx.tenant.review_context or {})
    rc.update(description=base.description or "", services=base.services)
    ctx.tenant.review_context = rc
    row = kbs.get_row(ctx.db, ctx.tenant)
    row.offers, row.hours, row.faqs = [o.model_dump() for o in body.offers], (body.hours or "").strip() or None, [f.model_dump() for f in body.faqs]
    row.brand_voice, row.approved_claims, row.prohibited_claims = (body.brand_voice or "").strip() or None, body.approved_claims, body.prohibited_claims
    row.updated_by = ctx.user.id
    audit(ctx.db, action="agent.knowledge_update", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="tenant", entity_id=ctx.tenant_id,
          meta={"services": len(base.services), "offers": len(body.offers), "faqs": len(body.faqs), "prohibited": len(body.prohibited_claims)}, ip=client_ip(request))
    ctx.db.commit()
    return _knowledge_out(ctx)


class CheckIn(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    kind: str = Field(default="post", pattern="^(reply|post|profile)$")


@router.post("/knowledge/check")
def check_text_against_knowledge(body: CheckIn, ctx: TenantContext = Depends(get_tenant_context)):
    """Run the same safety rules the AI output goes through on any text you type (used to preview what would be rejected)."""
    return {"violations": [v.as_dict() for v in check_text(body.text, kb=kbs.context(ctx.db, ctx.tenant), kind=body.kind)]}


# ------------------------------------------------------------------ health + overview
def _scope(ctx: TenantContext):
    return ctx.location_ids


@router.get("/health")
def health(ctx: TenantContext = Depends(get_tenant_context)):
    res = health_svc.compute(ctx.db, ctx.tenant, location_ids=_scope(ctx))
    out = health_svc.record_and_explain(ctx.db, ctx.tenant, res) if not ctx.restricted else {**res, "changes": [], "history": []}
    ctx.db.commit()
    return out


def _task_out(db, t: AgentTask) -> dict:
    d = {"id": str(t.id), "kind": t.kind, "title": t.title, "why": t.why, "evidence": t.evidence, "suggested_action": t.suggested_action, "status": t.status,
         "draft": t.draft, "ref_type": t.ref_type, "ref_id": str(t.ref_id) if t.ref_id else None, "priority": t.priority, "plan_date": t.plan_date.isoformat(),
         "snoozed_until": t.snoozed_until, "completed_at": t.completed_at, "failure_reason": t.failure_reason, "created_at": t.created_at,
         "location_id": str(t.location_id) if t.location_id else None}
    if t.ref_type == "reply_draft" and t.ref_id:
        rd = db.get(ReplyDraft, t.ref_id)
        d["reply"] = None if rd is None else {"id": str(rd.id), "body": rd.body, "status": rd.status.value, "flags": rd.flag_reasons, "review_id": str(rd.review_id)}
    if t.ref_type == "scheduled_post" and t.ref_id:
        p = db.get(ScheduledPost, t.ref_id)
        d["post"] = None if p is None else {"id": str(p.id), "summary": p.summary, "status": p.status, "scheduled_for": p.scheduled_for}
    return d


def _visible_tasks(ctx: TenantContext, q):
    """Tenant-wide tasks (no location) are hidden from location-restricted staff; location tasks only if it is theirs."""
    q = q.where(AgentTask.tenant_id == ctx.tenant_id)
    return q.where(ctx.scope(AgentTask.location_id)) if ctx.restricted else q


@router.get("/tasks")
def list_tasks(scope: str = Query("open", pattern="^(today|open|all|history)$"), kind: str | None = None, limit: int = Query(100, ge=1, le=300),
               ctx: TenantContext = Depends(get_tenant_context)):
    plan_svc.sync_tasks(ctx.db, ctx.tenant)
    ctx.db.flush()  # the listing below must see the moves just made
    q = _visible_tasks(ctx, select(AgentTask))
    today = plan_svc.tenant_today(ctx.tenant)
    if scope == "today":
        q = q.where(AgentTask.status.in_(plan_svc.OPEN) & (AgentTask.status != "snoozed") | (AgentTask.completed_at >= utcnow() - timedelta(hours=24)))
    elif scope == "open":
        q = q.where(AgentTask.status.in_(plan_svc.OPEN))
    elif scope == "history":
        q = q.where(AgentTask.status.in_(("published", "done", "dismissed")))
    if kind:
        q = q.where(AgentTask.kind == kind)
    rows = ctx.db.scalars(q.order_by(AgentTask.priority, AgentTask.created_at.desc()).limit(limit)).all()
    counts = dict(ctx.db.execute(_visible_tasks(ctx, select(AgentTask.status, func.count())).group_by(AgentTask.status)).all())
    ctx.db.commit()
    s = ctx.db.scalar(select(AgentSettings).where(AgentSettings.tenant_id == ctx.tenant_id))
    return {"tasks": [_task_out(ctx.db, t) for t in rows], "counts": counts, "plan_date": today.isoformat(), "last_plan_date": s.last_plan_date.isoformat() if s and s.last_plan_date else None}


def _task(ctx: TenantContext, task_id: uuid.UUID) -> AgentTask:
    t = ctx.db.scalar(select(AgentTask).where(AgentTask.id == task_id, AgentTask.tenant_id == ctx.tenant_id))
    if not t or not ctx.can_access_location(t.location_id):
        raise HTTPException(status_code=404, detail="Task not found")
    return t


def _wrap(fn):
    try:
        return fn()
    except plan_svc.TaskError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))
    except posts_svc.PostError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc))


@router.post("/plan/run")
def run_plan(request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Build today's plan now from current data (also runs daily on its own)."""
    ent.require_active(ctx.db, ctx.tenant_id)
    if not hit(f"plan:{ctx.tenant_id}", 6, 3600):
        raise HTTPException(status_code=429, detail="The plan was refreshed a few times already this hour. Try again later.")
    out = plan_svc.run_plan(ctx.db, ctx.tenant, manual=True)
    audit(ctx.db, action="agent.plan_run", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="tenant", entity_id=ctx.tenant_id, meta=out, ip=client_ip(request))
    ctx.db.commit()
    return out


@router.post("/google/refresh")
def refresh_google(request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Ask Google for the latest profile, posts, photos and performance of every connected location, and report what Google answered."""
    ent.require_active(ctx.db, ctx.tenant_id)
    if not hit(f"gsnap:{ctx.tenant_id}", 6, 3600):
        raise HTTPException(status_code=429, detail="Google was refreshed a few times already this hour. Try again later.")
    rows = list(ctx.db.scalars(select(GoogleLocation).join(GoogleConnection, GoogleConnection.id == GoogleLocation.connection_id).where(
        GoogleLocation.tenant_id == ctx.tenant_id, GoogleLocation.selected.is_(True), GoogleConnection.status == GoogleConnectionStatus.active, ctx.scope(GoogleLocation.location_id))))
    if not rows:
        raise HTTPException(status_code=409, detail="No connected Google location. Connect Google and choose a location first.")
    out = []
    for gl in rows:
        s = snap_svc.refresh(ctx.db, gl)
        out.append({"google_location_id": str(gl.id), "title": gl.title, "ok": s.error is None, "error": s.error, "fetched_at": s.fetched_at})
    ctx.db.add(AgentRun(tenant_id=ctx.tenant_id, kind="refresh_google", status="ok" if all(o["ok"] for o in out) else "failed", started_at=utcnow(), finished_at=utcnow(),
                        detail={"locations": len(out)}, error="; ".join(o["error"] for o in out if o["error"])[:500] or None))
    ctx.db.commit()
    return {"locations": out}


@router.post("/tasks/{task_id}/draft")
def draft_task(task_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    t = _task(ctx, task_id)
    ent.require_feature(ctx.db, ctx.tenant_id, {"reply_review": "ai_replies", "create_post": "gbp_posts", "profile_fix": "gbp_info"}.get(t.kind, "ai_replies"))
    try:
        provider = get_provider()
    except AIUnavailable:
        raise HTTPException(status_code=503, detail="AI is not configured on this server. Setup required: add an AI provider key.")
    try:
        _wrap(lambda: plan_svc.draft_for_task(ctx.db, ctx.tenant, t, provider, user_id=ctx.user.id))
    except HTTPException:
        ctx.db.rollback()
        raise
    except AIUnavailable as exc:
        ctx.db.commit()  # keeps the error log row
        raise HTTPException(status_code=502, detail="The AI couldn't write a safe draft. " + ("It broke a safety rule twice, so nothing is shown. " if exc.code == "rejected" else "") + "Try again, or write it yourself.")
    ctx.db.commit()
    return _task_out(ctx.db, t)


class SnoozeIn(BaseModel):
    days: int = Field(default=1, ge=1, le=30)


@router.post("/tasks/{task_id}/snooze")
def snooze(task_id: uuid.UUID, body: SnoozeIn, ctx: TenantContext = Depends(get_tenant_context)):
    t = _task(ctx, task_id)
    _wrap(lambda: plan_svc.transition(ctx.db, t, "snoozed", actor="user", user_id=ctx.user.id, note=f"Snoozed for {body.days} day(s)"))
    t.snoozed_until = utcnow() + timedelta(days=body.days)
    ctx.db.commit()
    return _task_out(ctx.db, t)


@router.post("/tasks/{task_id}/dismiss")
def dismiss(task_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    t = _task(ctx, task_id)
    _wrap(lambda: plan_svc.transition(ctx.db, t, "dismissed", actor="user", user_id=ctx.user.id, note="Dismissed by the owner"))
    ctx.db.commit()
    return _task_out(ctx.db, t)


class DraftEditIn(BaseModel):
    description: str = Field(min_length=40, max_length=750)


@router.patch("/tasks/{task_id}/draft")
def edit_draft(task_id: uuid.UUID, body: DraftEditIn, ctx: TenantContext = Depends(get_tenant_context)):
    """Edit the proposed description. Editing keeps it awaiting approval; it is only ever sent to Google by `approve`."""
    t = _task(ctx, task_id)
    if t.kind != "profile_fix" or t.status != "awaiting_approval":
        raise HTTPException(status_code=409, detail="Only a drafted profile description can be edited here.")
    t.draft = {"description": body.description.strip()}
    ctx.db.commit()
    return {**_task_out(ctx.db, t), "violations": [v.as_dict() for v in check_text(body.description, kb=kbs.context(ctx.db, ctx.tenant), kind="profile")]}


@router.post("/tasks/{task_id}/approve")
def approve_profile_task(task_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Owner/admin approval of a profile description. This is the ONLY step that writes it to Google, and the task is marked
    published only if Google's own response contains the new text."""
    t = _task(ctx, task_id)
    if t.kind != "profile_fix" or not (t.draft or {}).get("description"):
        raise HTTPException(status_code=409, detail="Replies and posts are approved on their own cards. Only profile descriptions are approved here.")
    ent.require_feature(ctx.db, ctx.tenant_id, "gbp_info")
    bad = check_text(t.draft["description"], kb=kbs.context(ctx.db, ctx.tenant), kind="profile")
    if bad:
        raise HTTPException(status_code=422, detail={"code": "safety_violation", "violations": [v.as_dict() for v in bad], "message": "This text breaks a rule from your knowledge base. Edit it first."})
    gl = ctx.db.get(GoogleLocation, uuid.UUID(t.evidence["google_location_id"]))
    if gl is None or gl.tenant_id != ctx.tenant_id or not ctx.can_access_location(gl.location_id):
        raise HTTPException(status_code=404, detail="Location not found")
    if not hit(f"gbp-edit:{gl.id}", 10, 60):
        raise HTTPException(status_code=429, detail="Google allows 10 profile edits per minute per location. Try again in a minute.")
    _wrap(lambda: plan_svc.execute_profile_description(ctx.db, t, gl, ctx.user.id))
    audit(ctx.db, action="agent.profile_description", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="agent_task", entity_id=t.id, meta={"result": t.status}, ip=client_ip(request))
    ctx.db.commit()
    return _task_out(ctx.db, t)


@router.get("/tasks/{task_id}/history")
def task_history(task_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    t = _task(ctx, task_id)
    ev = ctx.db.scalars(select(AgentTaskEvent).where(AgentTaskEvent.task_id == t.id).order_by(AgentTaskEvent.created_at)).all()
    return [{"from": e.from_status, "to": e.to_status, "actor": e.actor, "note": e.note, "at": e.created_at} for e in ev]


# ------------------------------------------------------------------ profile manager helpers
def _gloc_for(ctx: TenantContext, gid: uuid.UUID) -> GoogleLocation:
    gl = ctx.db.scalar(select(GoogleLocation).where(GoogleLocation.id == gid, GoogleLocation.tenant_id == ctx.tenant_id))
    if not gl or not gl.selected or not ctx.can_access_location(gl.location_id):
        raise HTTPException(status_code=404, detail="Google location not found")
    return gl


@router.get("/profile/{gid}")
def profile_state(gid: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    """Completeness of one location's Google profile, from the last time Google answered (with when), plus any pending description task."""
    gl = _gloc_for(ctx, gid)
    s = ctx.db.scalar(select(GbpSnapshot).where(GbpSnapshot.google_location_id == gl.id))
    task = ctx.db.scalar(select(AgentTask).where(AgentTask.tenant_id == ctx.tenant_id, AgentTask.dedupe_key == f"profile_description:{gl.id}", AgentTask.status.in_(plan_svc.OPEN)))
    return {"completeness": snap_svc.profile_completeness(s.info) if s and s.info else None, "fetched_at": s.fetched_at if s else None, "error": s.error if s else None,
            "task": _task_out(ctx.db, task) if task else None}


@router.post("/profile/{gid}/suggest-description")
def suggest_description(gid: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    """Ask the AI to write the 'About' text from the knowledge base. It becomes a task waiting for approval; nothing is sent to Google."""
    ent.require_feature(ctx.db, ctx.tenant_id, "gbp_info")
    gl = _gloc_for(ctx, gid)
    try:
        provider = get_provider()
    except AIUnavailable:
        raise HTTPException(status_code=503, detail="AI is not configured on this server. Setup required: add an AI provider key.")
    today = plan_svc.tenant_today(ctx.tenant)
    s = ctx.db.scalar(select(GbpSnapshot).where(GbpSnapshot.google_location_id == gl.id))
    t = ctx.db.scalar(select(AgentTask).where(AgentTask.tenant_id == ctx.tenant_id, AgentTask.dedupe_key == f"profile_description:{gl.id}", AgentTask.status.in_(plan_svc.OPEN)))
    if t is None:
        t = plan_svc._add(ctx.db, ctx.tenant, today, kind="profile_fix", title=f"Write a description for {gl.title or 'your profile'}", why="You asked for a suggested description.",
                          evidence={"field": "description", "google_location_id": str(gl.id), "current_length": len(((s.info or {}).get("description") or "").strip()) if s else None},
                          action="Edit the draft, then approve it to publish on Google.", dedupe=f"profile_description:{gl.id}", priority=35, location_id=gl.location_id)
    if t.status not in ("suggested", "failed"):
        return _task_out(ctx.db, t)
    try:
        _wrap(lambda: plan_svc.draft_for_task(ctx.db, ctx.tenant, t, provider, user_id=ctx.user.id))
    except HTTPException:
        ctx.db.rollback()
        raise
    except AIUnavailable as exc:
        ctx.db.commit()
        raise HTTPException(status_code=502, detail="The AI couldn't write a safe description. " + ("It broke a safety rule twice, so nothing is shown. " if exc.code == "rejected" else "") + "Try again, or write it yourself.")
    ctx.db.commit()
    return _task_out(ctx.db, t)


# ------------------------------------------------------------------ approvals
@router.get("/approvals")
def approvals(ctx: TenantContext = Depends(get_tenant_context)):
    """Everything waiting for a person: AI/hand-written reply drafts, posts, profile text. Each with the safety findings."""
    kb = kbs.context(ctx.db, ctx.tenant)
    replies = ctx.db.execute(select(ReplyDraft, Review).join(Review, Review.id == ReplyDraft.review_id).where(
        ReplyDraft.tenant_id == ctx.tenant_id, ReplyDraft.status == ReplyStatus.draft, Review.google_reply_text.is_(None), ctx.scope(Review.location_id)).order_by(ReplyDraft.created_at.desc()).limit(50)).all()
    posts = ctx.db.scalars(select(ScheduledPost).join(GoogleLocation, GoogleLocation.id == ScheduledPost.google_location_id).where(
        ScheduledPost.tenant_id == ctx.tenant_id, ScheduledPost.status == "awaiting_approval", ctx.scope(GoogleLocation.location_id)).order_by(ScheduledPost.created_at.desc()).limit(50)).all()
    profile = ctx.db.scalars(_visible_tasks(ctx, select(AgentTask)).where(AgentTask.kind == "profile_fix", AgentTask.status == "awaiting_approval").limit(20)).all()
    return {
        "replies": [{"id": str(d.id), "review_id": str(r.id), "rating": r.rating, "reviewer": r.reviewer_name, "review_text": (r.text or "")[:400], "body": d.body, "ai": d.generated_by_ai,
                     "flags": d.flag_reasons, "violations": [v.as_dict() for v in check_text(d.body, kb=kb, kind="reply")], "created_at": d.created_at} for d, r in replies],
        "posts": [{"id": str(p.id), "summary": p.summary, "ai": p.generated_by_ai, "scheduled_for": p.scheduled_for, "cta_type": p.cta_type, "violations": posts_svc.validate_content(p, kb), "created_at": p.created_at} for p in posts],
        "profile": [{**_task_out(ctx.db, t), "violations": [v.as_dict() for v in check_text((t.draft or {}).get("description", ""), kb=kb, kind="profile")]} for t in profile],
    }


# ------------------------------------------------------------------ activity
@router.get("/activity")
def activity(ctx: TenantContext = Depends(get_tenant_context)):
    runs = ctx.db.scalars(select(AgentRun).where(AgentRun.tenant_id == ctx.tenant_id).order_by(desc(AgentRun.started_at)).limit(40)).all()
    events = ctx.db.execute(select(AgentTaskEvent, AgentTask.title).join(AgentTask, AgentTask.id == AgentTaskEvent.task_id).where(AgentTaskEvent.tenant_id == ctx.tenant_id)
                            .order_by(desc(AgentTaskEvent.created_at)).limit(60)).all()
    failed_posts = ctx.db.scalars(select(ScheduledPost).where(ScheduledPost.tenant_id == ctx.tenant_id, ScheduledPost.status == "failed").order_by(desc(ScheduledPost.updated_at)).limit(20)).all()
    queued = ctx.db.scalars(select(ScheduledPost).where(ScheduledPost.tenant_id == ctx.tenant_id, ScheduledPost.status == "scheduled").order_by(ScheduledPost.scheduled_for).limit(20)).all()
    s = ctx.db.scalar(select(AgentSettings).where(AgentSettings.tenant_id == ctx.tenant_id))
    sub = ent.for_tenant(ctx.db, ctx.tenant_id)
    last = next((r for r in runs if r.kind == "daily_plan" and r.status != "running"), None)
    pending = ctx.db.scalar(select(func.count()).select_from(AgentTask).where(AgentTask.tenant_id == ctx.tenant_id, AgentTask.status == "awaiting_approval")) or 0
    return {
        "runs": [{"id": str(r.id), "kind": r.kind, "status": r.status, "started_at": r.started_at, "finished_at": r.finished_at, "detail": r.detail, "error": r.error} for r in runs],
        "events": [{"task": title, "from": e.from_status, "to": e.to_status, "actor": e.actor, "note": e.note, "at": e.created_at} for e, title in events],
        "failed_posts": [{"id": str(p.id), "summary": p.summary[:140], "reason": p.failure_reason, "attempts": p.attempts} for p in failed_posts],
        "queued_posts": [{"id": str(p.id), "summary": p.summary[:140], "scheduled_for": p.scheduled_for, "next_attempt_at": p.next_attempt_at, "attempts": p.attempts, "last_error": p.failure_reason} for p in queued],
        "last_plan_run": None if last is None else {"status": last.status, "at": last.started_at, "error": last.error},
        "last_plan_date": s.last_plan_date.isoformat() if s and s.last_plan_date else None, "pending_approvals": pending,
        "ai": {"used_this_month": usage_this_month(ctx.db, ctx.tenant_id), "monthly_limit": sub.monthly_ai_generations, "month_started": month_start().isoformat()},
    }


# ------------------------------------------------------------------ automation settings
class SettingsIn(BaseModel):
    daily_plan: bool | None = None
    auto_draft_replies: bool | None = None


def _settings_out(s: AgentSettings) -> dict:
    return {"daily_plan": s.daily_plan, "auto_draft_replies": s.auto_draft_replies, "auto_publish": False,
            "notes": {"auto_draft_replies": "New unanswered reviews get an AI draft prepared for your approval. Nothing is published without you.",
                      "auto_publish": "Automatic publishing is not available. Every reply, post and profile change needs a person's approval."}}


@router.get("/settings")
def get_settings(ctx: TenantContext = Depends(get_tenant_context)):
    s = plan_svc._settings(ctx.db, ctx.tenant_id)
    ctx.db.commit()
    return _settings_out(s)


@router.put("/settings")
def put_settings(body: SettingsIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    s = plan_svc._settings(ctx.db, ctx.tenant_id)
    changes = body.model_dump(exclude_none=True)
    for k, v in changes.items():
        setattr(s, k, v)
    audit(ctx.db, action="agent.settings", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="tenant", entity_id=ctx.tenant_id, meta=changes, ip=client_ip(request))
    ctx.db.commit()
    return _settings_out(s)
