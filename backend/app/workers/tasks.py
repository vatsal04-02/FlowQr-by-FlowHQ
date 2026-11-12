import logging
import uuid
from datetime import timedelta

from app.core.db import system_session
from app.models import GoogleLocation
from app.services import google as g
from app.services.google.sync import due_locations, sync_google_location
from app.workers.celery_app import celery_app

log = logging.getLogger("flowqr.tasks")


@celery_app.task(name="flowqr.sync_location", bind=True, autoretry_for=(Exception,), retry_backoff=60, retry_backoff_max=900, retry_jitter=True, max_retries=3)
def sync_location(self, google_location_id: str):
    db = system_session()
    try:
        gloc = db.get(GoogleLocation, uuid.UUID(google_location_id))
        if not gloc:
            return {"status": "missing"}
        return sync_google_location(db, gloc)
    except g.GoogleNotConfigured:
        return {"status": "not_configured"}
    finally:
        db.close()


@celery_app.task(name="flowqr.sync_due_locations")
def sync_due_locations():
    db = system_session()
    try:
        ids = [str(x.id) for x in due_locations(db)]
    finally:
        db.close()
    for gid in ids:
        sync_location.delay(gid)
    return {"queued": len(ids)}


@celery_app.task(name="flowqr.billing_refresh")
def billing_refresh():
    from app.services.billing import refresh_statuses

    db = system_session()
    try:
        return refresh_statuses(db)
    finally:
        db.close()


@celery_app.task(name="flowqr.purge_review_sessions")
def purge_review_sessions():
    """Delete customer answers and drafts past the retention period (analytics events are kept; they hold no text)."""
    from app.services.review_growth import purge_expired

    db = system_session()
    try:
        return {"purged": purge_expired(db)}
    finally:
        db.close()


@celery_app.task(name="flowqr.retry_failed_replies")
def retry_failed_replies():
    """Re-attempt replies that a human approved but Google rejected for a *transient* reason (429/5xx).

    Never touches unapproved drafts. Row-locked (skip_locked) so overlapping runs or a user clicking Retry can't double-publish.
    """
    from sqlalchemy import select

    from app.core.deps import member_may_act
    from app.models import ReplyDraft, ReplyLog, ReplyStatus, Review, Role
    from app.services import entitlements as ent
    from app.services.reviews import publish_draft

    db = system_session()
    done = 0
    try:
        ids = db.scalars(select(ReplyDraft.id).where(ReplyDraft.status == ReplyStatus.failed, ReplyDraft.approved_by.is_not(None), ReplyDraft.attempts < 4)).all()
        for did in ids:
            d = db.scalar(select(ReplyDraft).where(ReplyDraft.id == did).with_for_update(skip_locked=True))
            if not d or d.status != ReplyStatus.failed:
                continue
            last = db.scalar(select(ReplyLog).where(ReplyLog.draft_id == d.id).order_by(ReplyLog.created_at.desc()).limit(1))
            transient = last is not None and (last.http_status == 429 or (last.http_status or 0) >= 500)
            review = db.get(Review, d.review_id)
            still_allowed = member_may_act(db, d.tenant_id, d.approved_by, review.location_id, Role.admin)
            if not transient or review.google_reply_text is not None or not ent.for_tenant(db, d.tenant_id).active or not still_allowed:
                db.rollback()
                continue
            try:
                publish_draft(db, d, by_user=d.approved_by)
                done += 1
            except Exception:  # keep the worker alive; the draft stays 'failed' for manual retry
                db.rollback()
                log.exception("auto-retry of reply %s failed", did)
        return {"retried": done}
    finally:
        db.close()


@celery_app.task(name="flowqr.purge_deleted_accounts")
def purge_deleted_accounts():
    """Delete businesses whose owner scheduled deletion and whose grace period has ended."""
    from app.services.account import delete_tenant, due_for_deletion

    db = system_session()
    try:
        ids = due_for_deletion(db)
        done = []
        for tid in ids:
            try:
                done.append(delete_tenant(db, tid))
            except Exception:  # keep going: one failure must not block the others, and it retries next hour
                db.rollback()
                log.exception("account deletion failed for %s", tid)
        return {"due": len(ids), "deleted": sum(1 for d in done if d.get("deleted"))}
    finally:
        db.close()


@celery_app.task(name="flowqr.publish_due_posts")
def publish_due_posts():
    """Publish approved posts whose time has come. One post at a time, each in its own transaction, so a slow Google call never
    holds other posts' locks and a crash loses at most the post in hand (it is picked up again, never published twice)."""
    from app.models.base import utcnow
    from app.services import entitlements as ent
    from app.services.agent import posts as posts_svc
    from app.services.audit import audit

    db = system_session()
    totals = {"published": 0, "retry": 0, "failed": 0, "skipped": 0, "held": 0}
    try:
        seen: set = set()
        for _ in range(40):
            batch = [p for p in posts_svc.due(db, limit=5) if p.id not in seen]
            if not batch:
                db.rollback()
                break
            p = batch[0]
            seen.add(p.id)
            if not ent.for_tenant(db, p.tenant_id).has("gbp_posts"):
                if p.scheduled_for and p.scheduled_for < utcnow() - timedelta(hours=24):  # a day late: too stale to publish unannounced
                    p.status, p.failure_reason = "failed", "The plan was inactive for more than a day after this post was due, so it was not published. Retry it if it is still relevant."
                    totals["failed"] += 1
                else:
                    totals["held"] += 1
                db.commit()
                continue
            res = posts_svc.publish(db, p)
            audit(db, action=f"post.publish_{res}", tenant_id=p.tenant_id, entity_type="scheduled_post", entity_id=p.id, meta={"status": p.status, "reason": p.failure_reason, "scheduled": True})
            totals[res] += 1
            db.commit()
        return totals
    finally:
        db.close()


@celery_app.task(name="flowqr.daily_agent")
def daily_agent():
    """Once a day per business (from 06:00 local time): refresh what Google says, then build the plan. A failure for one business
    is recorded on its own activity log and never stops the others."""
    from zoneinfo import ZoneInfo

    from sqlalchemy import select

    from app.models import AgentSettings, GoogleConnection, GoogleConnectionStatus, GoogleLocation, Tenant
    from app.models.base import utcnow
    from app.services import entitlements as ent
    from app.services.agent import plan as plan_svc
    from app.services.agent import snapshots as snap_svc

    db = system_session()
    ran = failed = 0
    try:
        for tid in list(db.scalars(select(Tenant.id).where(Tenant.is_active.is_(True), Tenant.suspended_at.is_(None), Tenant.deletion_scheduled_for.is_(None)))):
            try:
                t = db.get(Tenant, tid)
                now_local = utcnow().astimezone(ZoneInfo(t.timezone or "Asia/Kolkata"))
                s = db.scalar(select(AgentSettings).where(AgentSettings.tenant_id == tid))
                if now_local.hour < 6 or (s and (not s.daily_plan or s.last_plan_date == now_local.date())) or not ent.for_tenant(db, tid).active:
                    continue
                for gl in db.scalars(select(GoogleLocation).join(GoogleConnection, GoogleConnection.id == GoogleLocation.connection_id).where(
                        GoogleLocation.tenant_id == tid, GoogleLocation.selected.is_(True), GoogleConnection.status == GoogleConnectionStatus.active)):
                    snap_svc.refresh(db, gl)
                plan_svc.run_plan(db, t)
                ran += 1
            except Exception:  # noqa: BLE001
                db.rollback()
                failed += 1
                log.exception("daily agent failed for tenant %s", tid)
        return {"ran": ran, "failed": failed}
    finally:
        db.close()
