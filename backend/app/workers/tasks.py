import logging
import uuid

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
