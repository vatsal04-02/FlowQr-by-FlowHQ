"""The daily plan and the task state machine.

Tasks are created only from things that are true right now (an unanswered review, a missing profile field, no recent post...). Each
task keeps the numbers it was based on. A task reaches `published`/`done` only after the thing really happened: Google confirmed a
reply or post, or a later sync/snapshot shows the problem gone. Nothing is published by this module without a person having approved it.
"""
import logging
import time
import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    AgentRun, AgentSettings, AgentTask, AgentTaskEvent, GbpSnapshot, GoogleConnection, GoogleConnectionStatus, GoogleLocation, Location, ReplyDraft,
    ReplyStatus, Review, ScheduledPost, Tenant,
)
from app.models.base import utcnow
from app.services import google as g
from app.services.agent import knowledge as kbs
from app.services.agent import posts as posts_svc
from app.services.agent.safety import check_text
from app.services.agent.snapshots import DESCRIPTION_MIN, profile_completeness
from app.services.ai.base import AIUnavailable, LLMProvider, get_provider
from app.services.ai.replies import draft_reply
from app.services.ai_usage import log_generation, quota_exceeded
from app.services.google.tokens import get_access_token

log = logging.getLogger("flowqr.agent")
MAX_NEW_PER_RUN = 8
MAX_REPLY_TASKS = 5
OPEN = ("suggested", "drafted", "awaiting_approval", "approved", "scheduled", "failed", "snoozed")

TRANSITIONS: dict[str, set[str]] = {
    "suggested": {"drafted", "snoozed", "dismissed", "done", "awaiting_approval", "published"},
    "drafted": {"awaiting_approval", "dismissed", "suggested"},
    "awaiting_approval": {"approved", "suggested", "dismissed", "published", "done", "scheduled", "failed"},
    "approved": {"scheduled", "published", "failed", "awaiting_approval", "suggested", "dismissed"},
    "scheduled": {"published", "failed", "awaiting_approval", "dismissed", "approved"},
    "failed": {"suggested", "awaiting_approval", "approved", "scheduled", "dismissed", "published", "done"},
    "snoozed": {"suggested", "dismissed", "done"},
    "published": set(), "dismissed": set(), "done": set(),
}
TERMINAL = {"published", "dismissed", "done"}


class TaskError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def transition(db: Session, task: AgentTask, to: str, *, actor: str, user_id: uuid.UUID | None = None, note: str | None = None) -> bool:
    """Move a task along the state machine and record who/why. Returns False when it is already there. Illegal moves raise."""
    if task.status == to:
        return False
    if to not in TRANSITIONS.get(task.status, set()):
        raise TaskError(f"A task that is {task.status.replace('_', ' ')} cannot become {to.replace('_', ' ')}.")
    db.add(AgentTaskEvent(tenant_id=task.tenant_id, task_id=task.id, from_status=task.status, to_status=to, actor=actor, user_id=user_id, note=note))
    task.status = to
    if to in TERMINAL:
        task.completed_at = utcnow()
    return True


def _settings(db: Session, tenant_id: uuid.UUID) -> AgentSettings:
    s = db.scalar(select(AgentSettings).where(AgentSettings.tenant_id == tenant_id))
    if s is None:
        s = AgentSettings(tenant_id=tenant_id)
        db.add(s)
        db.flush()
    return s


def tenant_today(tenant: Tenant, now: datetime | None = None) -> date:
    return (now or utcnow()).astimezone(ZoneInfo(tenant.timezone or "Asia/Kolkata")).date()


def _add(db: Session, tenant: Tenant, today: date, *, kind: str, title: str, why: str, evidence: dict, action: str, dedupe: str, priority: int,
         location_id: uuid.UUID | None = None, status: str = "suggested", ref: tuple[str, uuid.UUID] | None = None, draft: dict | None = None) -> AgentTask | None:
    """Create a task unless an open one with the same dedupe key exists (the partial unique index enforces it too)."""
    if db.scalar(select(AgentTask.id).where(AgentTask.tenant_id == tenant.id, AgentTask.dedupe_key == dedupe, AgentTask.status.in_(OPEN))):
        return None
    t = AgentTask(tenant_id=tenant.id, location_id=location_id, kind=kind, title=title[:200], why=why, evidence=evidence, suggested_action=action, status="suggested",
                  dedupe_key=dedupe[:120], priority=priority, plan_date=today, draft=draft, ref_type=ref[0] if ref else None, ref_id=ref[1] if ref else None)
    try:
        with db.begin_nested():
            db.add(t)
            db.flush()
    except IntegrityError:
        return None
    db.add(AgentTaskEvent(tenant_id=tenant.id, task_id=t.id, from_status=None, to_status="suggested", actor="agent", note="Created from current data"))
    if status != "suggested":
        transition(db, t, status, actor="agent", note="Existing draft found")
    return t


def _active_glocs(db: Session, tenant: Tenant) -> list[GoogleLocation]:
    return list(db.scalars(select(GoogleLocation).join(GoogleConnection, GoogleConnection.id == GoogleLocation.connection_id).where(
        GoogleLocation.tenant_id == tenant.id, GoogleLocation.selected.is_(True), GoogleConnection.status == GoogleConnectionStatus.active)))


def sync_tasks(db: Session, tenant: Tenant, *, now: datetime | None = None) -> dict:
    """Bring open tasks in line with reality: what Google/our records now say. Nothing is assumed."""
    now = now or utcnow()
    moved = 0
    glocs = {g_.id: g_ for g_ in _active_glocs(db, tenant)}
    snaps = {s.google_location_id: s for s in db.scalars(select(GbpSnapshot).where(GbpSnapshot.tenant_id == tenant.id))}
    kb = kbs.context(db, tenant)
    for t in db.scalars(select(AgentTask).where(AgentTask.tenant_id == tenant.id, AgentTask.status.in_(OPEN))):
        if t.status == "snoozed" and t.snoozed_until and t.snoozed_until <= now:
            moved += transition(db, t, "suggested", actor="system", note="Snooze ended")
            continue
        if t.kind == "reply_review" and t.evidence.get("review_id"):
            rv = db.get(Review, uuid.UUID(t.evidence["review_id"]))
            d = db.get(ReplyDraft, t.ref_id) if t.ref_type == "reply_draft" and t.ref_id else None
            if rv is not None and rv.google_reply_text is not None and rv.google_reply_state != "REJECTED":
                ours = d is not None and d.status == ReplyStatus.published
                moved += transition(db, t, "published" if ours else "done", actor="google" if ours else "system",
                                    note="Google shows the reply" if ours else "A reply now exists on Google")
            elif d is not None:
                want = {ReplyStatus.draft: "awaiting_approval", ReplyStatus.approved: "approved", ReplyStatus.failed: "failed", ReplyStatus.rejected: "suggested"}.get(d.status)
                if want and want != t.status and want in TRANSITIONS[t.status]:
                    if want == "failed":
                        t.failure_reason = d.failure_reason
                    if want == "suggested":
                        t.ref_type = t.ref_id = None
                    moved += transition(db, t, want, actor="system", note="Follows the reply draft")
        elif t.kind == "create_post" and t.ref_type == "scheduled_post" and t.ref_id:
            p = db.get(ScheduledPost, t.ref_id)
            want = None if p is None else {"draft": "awaiting_approval", "awaiting_approval": "awaiting_approval", "approved": "approved", "scheduled": "scheduled", "publishing": "scheduled",
                                           "published": "published", "failed": "failed", "canceled": "dismissed"}[p.status]
            if p is not None and p.status == "failed":
                t.failure_reason = p.failure_reason
            if want and want != t.status and want in TRANSITIONS[t.status]:
                moved += transition(db, t, want, actor="google" if want == "published" else "system", note="Follows the post")
        elif t.kind == "connect_google" and glocs:
            moved += transition(db, t, "done", actor="system", note="Google is connected with a location")
        elif t.kind == "complete_knowledge" and kbs.completeness(kb)["complete"]:
            moved += transition(db, t, "done", actor="system", note="Knowledge base is complete")
        elif t.kind in ("profile_fix", "add_photo") and t.evidence.get("google_location_id"):
            gid = uuid.UUID(t.evidence["google_location_id"])
            s = snaps.get(gid)
            if s is None or s.fetched_at is None or s.fetched_at <= t.created_at:
                continue  # only a refresh made after the task was created can show it is solved
            if t.kind == "add_photo" and s.media and any((c := (m.get("created_at") or "")) and c >= t.created_at.isoformat()[:19] for m in s.media):
                moved += transition(db, t, "done", actor="google", note="A newer photo now exists on the profile")
            elif t.kind == "profile_fix" and s.info is not None:
                field = t.evidence.get("field")
                done = (field == "description" and len((s.info.get("description") or "").strip()) >= DESCRIPTION_MIN) or \
                       (field == "missing" and not profile_completeness(s.info)["missing"])
                if done:
                    moved += transition(db, t, "published" if t.status in ("approved", "scheduled") else "done", actor="google", note="Google's profile now has it")
    return {"moved": moved}


def generate(db: Session, tenant: Tenant, *, now: datetime | None = None, manual: bool = False, provider: LLMProvider | None = None) -> dict:
    """Create today's tasks from real data, resolve finished ones, optionally draft replies. Returns a summary and records an AgentRun."""
    now = now or utcnow()
    today = tenant_today(tenant, now)
    settings_row = _settings(db, tenant.id)
    run = AgentRun(tenant_id=tenant.id, kind="daily_plan", status="running", started_at=now, detail={"manual": manual})
    db.add(run)
    db.flush()
    created: list[AgentTask] = []
    try:
        if not settings_row.daily_plan and not manual:
            run.status, run.detail = "ok", {"skipped": "daily plan is turned off"}
            run.finished_at = utcnow()
            return {"created": 0, "skipped": True}
        sync_tasks(db, tenant, now=now)
        kb = kbs.context(db, tenant)
        glocs = _active_glocs(db, tenant)
        snaps = {s.google_location_id: s for s in db.scalars(select(GbpSnapshot).where(GbpSnapshot.tenant_id == tenant.id))}

        def add(**kw):
            if len(created) < MAX_NEW_PER_RUN and (t := _add(db, tenant, today, **kw)):
                created.append(t)

        # Google connection
        conn = db.scalar(select(GoogleConnection).where(GoogleConnection.tenant_id == tenant.id, GoogleConnection.status != GoogleConnectionStatus.disconnected).order_by(GoogleConnection.created_at))
        if not glocs:
            if conn is None:
                add(kind="connect_google", title="Connect your Google Business Profile", why="No Google account is connected, so reviews, posts and performance cannot be read.",
                    evidence={"state": "not_connected"}, action="Open Google Business → Overview and connect the account that manages your listing.", dedupe="connect_google", priority=20)
            elif conn.api_access in ("awaiting_approval", "api_disabled"):
                add(kind="connect_google", title="Google access isn't ready yet", why=conn.last_error or "Google has not enabled Business Profile access for FlowQR's project.",
                    evidence={"state": conn.api_access}, action="Nothing to do in FlowQR yet; this clears once Google approves access.", dedupe="connect_google", priority=20)
            else:
                add(kind="connect_google", title="Choose a location to manage", why="Your Google account is connected but no location is selected, or none was found on that account.",
                    evidence={"state": "no_locations"}, action="Select a location, or connect another Google account that manages one.", dedupe="connect_google", priority=20)
        # Knowledge base
        comp = kbs.completeness(kb)
        if not comp["complete"]:
            add(kind="complete_knowledge", title="Complete your knowledge base", why=f"The AI can only write about facts you give it. Missing: {', '.join(comp['missing'])}.",
                evidence={"missing": comp["missing"]}, action="Add them on the Knowledge Base page.", dedupe="complete_knowledge", priority=25)
        # Unanswered reviews
        loc_ids = {g_.location_id for g_ in glocs if g_.location_id}
        rq = select(Review).where(Review.tenant_id == tenant.id, Review.google_reply_text.is_(None), Review.review_created_at >= now - timedelta(days=90))
        for rv in db.scalars(rq.order_by(Review.rating.asc(), Review.review_created_at.asc()).limit(MAX_REPLY_TASKS)):
            age = (now - rv.review_created_at).days
            d = db.scalar(select(ReplyDraft).where(ReplyDraft.review_id == rv.id, ReplyDraft.status.in_([ReplyStatus.draft, ReplyStatus.approved])).order_by(ReplyDraft.created_at.desc()).limit(1))
            add(kind="reply_review", title=f"Reply to a {rv.rating}-star review from {rv.reviewer_name or 'a customer'}",
                why=f"This {rv.rating}-star review is {age} day{'s' if age != 1 else ''} old and has no reply.",
                evidence={"review_id": str(rv.id), "rating": rv.rating, "age_days": age, "reviewer": rv.reviewer_name, "snippet": (rv.text or "")[:140]},
                action="Draft a reply from your knowledge base, edit it, then approve.", dedupe=f"reply:{rv.id}", priority=10 if rv.rating <= 2 else 40, location_id=rv.location_id,
                status="awaiting_approval" if d and d.status == ReplyStatus.draft else "approved" if d else "suggested", ref=("reply_draft", d.id) if d else None)
        # Posts
        last_post = None
        known = any(s.posts is not None for s in snaps.values())
        for s in snaps.values():
            for p in s.posts or []:
                c = p.get("created_at")
                if c and (last_post is None or c > last_post):
                    last_post = c
        ours = db.scalar(select(ScheduledPost.published_at).where(ScheduledPost.tenant_id == tenant.id, ScheduledPost.status == "published").order_by(ScheduledPost.published_at.desc()).limit(1))
        last_iso = max([x for x in (last_post, ours.isoformat() if ours else None) if x], default=None)
        days = (now - datetime.fromisoformat(last_iso.replace("Z", "+00:00"))).days if last_iso else None
        if glocs and ((known and (days is None or days >= 14)) or (not known and ours is None)):
            week = f"{today.isocalendar().year}-{today.isocalendar().week}"
            add(kind="create_post", title="Publish a Google post this week",
                why=(f"Your last post was {days} days ago." if days is not None else "No post is visible on your profile." if known else "FlowQR can't see your Google posts yet and none has been published from FlowQR."),
                evidence={"days_since_last_post": days, "google_posts_known": known}, action="Draft a post from your knowledge base, edit it, approve it and choose when it goes out.",
                dedupe=f"post:{week}", priority=45, location_id=glocs[0].location_id)
        # Profile and photos, per location, only from real snapshots
        for gl in glocs:
            s = snaps.get(gl.id)
            if not s or not s.fetched_at:
                continue
            if s.info is not None:
                pc = profile_completeness(s.info)
                keys = {m["key"] for m in pc["missing"]}
                if "description" in keys:
                    add(kind="profile_fix", title=f"Add a description to {gl.title or 'your profile'}", why=f"Your Google description is missing or shorter than {DESCRIPTION_MIN} characters.",
                        evidence={"field": "description", "google_location_id": str(gl.id), "current_length": len((s.info.get("description") or "").strip())},
                        action="Draft a description from your knowledge base, edit it and approve it. It goes live on Google only after you approve.", dedupe=f"profile_description:{gl.id}", priority=35, location_id=gl.location_id)
                rest = [m for m in pc["missing"] if m["key"] != "description"]
                if rest:
                    add(kind="profile_fix", title=f"Complete {gl.title or 'your profile'}: {', '.join(m['label'].lower() for m in rest)}",
                        why="These fields are empty on your Google profile.", evidence={"field": "missing", "google_location_id": str(gl.id), "missing": [m["label"] for m in rest]},
                        action="Add them in Profile Manager.", dedupe=f"profile_missing:{gl.id}", priority=38, location_id=gl.location_id)
            if s.media is not None:
                newest = max((m["created_at"] for m in s.media if m.get("created_at")), default=None)
                age = (now - datetime.fromisoformat(newest.replace("Z", "+00:00"))).days if newest else None
                if age is None or age > 90:
                    add(kind="add_photo", title=f"Add a fresh photo to {gl.title or 'your profile'}", why=("No photos are on your profile." if age is None else f"Your newest photo is {age} days old."),
                        evidence={"newest_photo_age_days": age, "google_location_id": str(gl.id)}, action="Upload a recent photo in Photos & Media.", dedupe=f"photo:{gl.id}", priority=60, location_id=gl.location_id)
        # Auto-draft replies (drafts only: publishing always needs a person)
        drafted = 0
        if settings_row.auto_draft_replies:
            prov = provider
            for t in db.scalars(select(AgentTask).where(AgentTask.tenant_id == tenant.id, AgentTask.kind == "reply_review", AgentTask.status == "suggested").order_by(AgentTask.priority).limit(MAX_REPLY_TASKS)):
                try:
                    prov = prov or get_provider()
                    draft_for_task(db, tenant, t, prov, user_id=None, actor="agent")
                    drafted += 1
                except (TaskError, AIUnavailable) as exc:
                    log.info("auto-draft skipped: %s", exc)
                    break
        settings_row.last_plan_date = today
        run.status = "ok"
        run.detail = {"manual": manual, "created": len(created), "drafted": drafted, "plan_date": today.isoformat()}
        run.finished_at = utcnow()
        return {"created": len(created), "drafted": drafted}
    except Exception as exc:  # noqa: BLE001 - recorded, never silent
        run.status, run.error, run.finished_at = "failed", f"{type(exc).__name__}: {exc}"[:500], utcnow()
        raise


def _loc_name(db: Session, location_id: uuid.UUID | None) -> str | None:
    loc = db.get(Location, location_id) if location_id else None
    return loc.name if loc else None


def draft_for_task(db: Session, tenant: Tenant, task: AgentTask, provider: LLMProvider, *, user_id: uuid.UUID | None, actor: str = "user") -> AgentTask:
    """Have the AI write the draft for a task. The result waits for approval; nothing is sent anywhere."""
    if task.status not in ("suggested", "failed"):
        raise TaskError("This task already has a draft or is finished.")
    if quota_exceeded(db, tenant.id):
        raise TaskError("Your monthly AI limit for this plan has been reached.", 402)
    kb = kbs.context(db, tenant)
    started = time.monotonic()
    try:
        if task.kind == "reply_review":
            rv = db.get(Review, uuid.UUID(task.evidence["review_id"]))
            if rv is None or rv.google_reply_text is not None:
                raise TaskError("That review is already answered or no longer exists.")
            body, lang, reasons = draft_reply(provider, rv, tenant, _loc_name(db, rv.location_id), kb=kb)
            d = ReplyDraft(tenant_id=tenant.id, review_id=rv.id, body=body, language=lang, generated_by_ai=True, created_by=user_id, requires_human_handling=bool(reasons), flag_reasons=reasons, status=ReplyStatus.draft)
            db.add(d)
            db.flush()
            task.ref_type, task.ref_id = "reply_draft", d.id
            out_chars = len(body)
        elif task.kind == "create_post":
            gl = next(iter(_active_glocs(db, tenant)), None)
            if gl is None:
                raise TaskError("Connect Google and choose a location before drafting a post.")
            recent = [p.summary for p in db.scalars(select(ScheduledPost).where(ScheduledPost.tenant_id == tenant.id).order_by(ScheduledPost.created_at.desc()).limit(5))]
            text, _ = posts_svc.draft_post(provider, tenant, kb, avoid=recent)
            p = ScheduledPost(tenant_id=tenant.id, google_location_id=gl.id, summary=text, language=tenant.language if tenant.language in ("en", "hi") else "en",
                              status="draft", generated_by_ai=True, created_by=user_id)
            db.add(p)
            db.flush()
            posts_svc.move(p, "awaiting_approval")
            task.ref_type, task.ref_id = "scheduled_post", p.id
            out_chars = len(text)
        elif task.kind == "profile_fix" and task.evidence.get("field") == "description":
            text = provider.generate(
                "You write the 'About' description for a Google Business Profile. 400 to 700 characters, plain text, factual, friendly. Use ONLY the facts provided; "
                "never invent services, prices, offers, results, awards or opening times. No claims about outcomes. Output ONLY the description.",
                kbs.render(kb) + "\n\nWrite the description.", max_tokens=400, temperature=0.4).strip().strip('"').strip()
            bad = check_text(text, kb=kb, kind="profile")
            if bad or len(text) < 60:
                raise AIUnavailable("The description broke a safety rule or was too short, so it was not shown", code="rejected")
            task.draft = {"description": text[:750]}
            out_chars = len(text)
        else:
            raise TaskError("This kind of task has no AI draft: follow the suggested action.")
    except AIUnavailable as exc:
        log_generation(db, tenant_id=tenant.id, kind="agent_draft", provider=provider.name, model=provider.model, language=None, input_chars=0, output_chars=0, status="error",
                       started=started, location_id=task.location_id, error=str(exc))
        raise
    log_generation(db, tenant_id=tenant.id, kind="agent_draft", provider=provider.name, model=provider.model, language=tenant.language, input_chars=0, output_chars=out_chars,
                   status="ok", started=started, location_id=task.location_id)
    transition(db, task, "drafted", actor=actor, user_id=user_id, note="AI draft written from the knowledge base")
    transition(db, task, "awaiting_approval", actor=actor, user_id=user_id, note="Waiting for the owner")
    return task


def execute_profile_description(db: Session, task: AgentTask, gloc: GoogleLocation, user_id: uuid.UUID, *, provider=None) -> AgentTask:
    """Owner approved the description: write it to Google. The task is `published` only if Google's reply confirms it."""
    if task.status != "awaiting_approval" or not (task.draft or {}).get("description"):
        raise TaskError("There is no approved-ready description for this task.")
    text = task.draft["description"]
    conn = db.get(GoogleConnection, gloc.connection_id)
    transition(db, task, "approved", actor="user", user_id=user_id, note="Owner approved the text")
    try:
        provider = provider or g.get_google_provider()
        token = get_access_token(db, conn, provider)
        after = provider.update_location(token, gloc.google_location_name, {"description": text})
    except Exception as exc:  # noqa: BLE001
        reason, _ = posts_svc.describe_failure(exc)
        task.failure_reason = reason
        transition(db, task, "failed", actor="google", note=reason)
        return task
    if (after or {}).get("description", "").strip() == text.strip():
        transition(db, task, "published", actor="google", user_id=user_id, note="Google returned the new description")
    else:
        task.failure_reason = "Google accepted the request but its profile does not show the new description yet."
        transition(db, task, "failed", actor="google", note=task.failure_reason)
    return task


def run_plan(db: Session, tenant: Tenant, *, manual: bool = False, provider: LLMProvider | None = None) -> dict:
    """generate() with the failure kept on record: whatever was created before an error is kept, and the run is stored as failed."""
    try:
        out = generate(db, tenant, manual=manual, provider=provider)
        db.commit()
        return out
    except Exception:
        try:
            db.commit()  # keeps the tasks created so far and the AgentRun marked failed
        except Exception:  # noqa: BLE001
            db.rollback()
        raise
