"""Review synchronisation. Idempotent upsert keyed on (google_location_id, Google review id)."""
import logging
import time
from dataclasses import replace
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    GoogleConnection, GoogleConnectionStatus, GoogleLocation, ReplyDraft, ReplyStatus, Review,
)
from app.models.base import utcnow
from app.services import google as g
from app.services.google.tokens import get_access_token, note_api_access

log = logging.getLogger("flowqr.sync")
MAX_PAGES = 40
REQUEST_RETRIES = 3


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def with_backoff(fn, *, sleep=None, attempts: int = REQUEST_RETRIES):
    """Retry transient failures (429, 5xx) with exponential backoff: 1s, 2s, 4s (capped by Retry-After)."""
    sleep = sleep or time.sleep  # resolved at call time (overridable in tests)
    for i in range(attempts):
        try:
            return fn()
        except g.GoogleRateLimited as exc:
            if i == attempts - 1:
                raise
            sleep(min(exc.retry_after or 2 ** i, 30))
        except g.GoogleAPIError as exc:
            if not exc.transient or i == attempts - 1:
                raise
            sleep(2 ** i)


def upsert_review(db: Session, gloc: GoogleLocation, gr: g.provider.GReview) -> str:
    """Returns 'new' | 'updated' | 'unchanged'."""
    existing = db.scalar(select(Review).where(Review.google_location_id == gloc.id, Review.external_id == gr.external_id))
    created, updated = _parse(gr.created_at), _parse(gr.updated_at)
    reply_at = _parse(gr.reply_updated_at)
    reply_state, violation = getattr(gr, "reply_state", None), getattr(gr, "reply_policy_violation", None)
    rejected_text = gr.reply_text if reply_state == "REJECTED" else None
    if reply_state == "REJECTED":  # Google refused the owner reply: it is not public, so it must not be shown as one
        gr = replace(gr, reply_text=None)
        reply_at = None
    if existing is None:
        rv = Review(
            tenant_id=gloc.tenant_id, location_id=gloc.location_id, google_location_id=gloc.id, external_id=gr.external_id,
            rating=gr.rating, text=gr.text, reviewer_name=gr.reviewer_name, review_created_at=created,
            review_updated_at=updated, first_seen_at=utcnow(), google_fetched_at=utcnow(), google_reply_text=gr.reply_text, google_reply_at=reply_at,
            google_reply_state=reply_state, google_reply_policy_violation=violation,
        )
        db.add(rv)
        db.flush()
        _reconcile_drafts(db, rv, rejected_text)
        return "new"
    if existing.google_content_expired_at is not None:
        return "unchanged"  # its content was expired under the retention period: it is NOT filled in again (that would restart a storage clock that must not move)
    changed = (existing.rating != gr.rating or existing.text != gr.text or existing.reviewer_name != gr.reviewer_name
               or existing.google_reply_text != gr.reply_text or existing.location_id != gloc.location_id
               or existing.google_reply_state != reply_state or existing.google_reply_policy_violation != violation)
    if not changed:
        return "unchanged"
    content_changed = existing.rating != gr.rating or existing.text != gr.text
    existing.rating, existing.text, existing.reviewer_name = gr.rating, gr.text, gr.reviewer_name
    existing.review_updated_at = updated
    existing.google_reply_text, existing.google_reply_at = gr.reply_text, reply_at
    existing.google_reply_state, existing.google_reply_policy_violation = reply_state, violation
    existing.location_id = gloc.location_id
    if content_changed:
        existing.update_count += 1
    _reconcile_drafts(db, existing, rejected_text)
    return "updated"


def rejection_message(violation: str | None) -> str:
    detail = " (" + violation.replace("_", " ").lower() + ")" if violation else ""
    return "Google rejected this reply" + detail + ". It is not visible to customers. Edit it and publish again."


def _reconcile_drafts(db: Session, rv: Review, rejected_text: str | None = None) -> None:
    """If Google now shows our approved reply, mark the draft published - confirmed by Google, not by us.
    If Google moderated our reply away (REJECTED), the draft that claimed 'published' is corrected to failed."""
    if rejected_text is not None:
        for d in db.scalars(select(ReplyDraft).where(ReplyDraft.review_id == rv.id, ReplyDraft.status.in_([ReplyStatus.published, ReplyStatus.approved]))):
            if d.body.strip() == rejected_text.strip():
                d.status, d.published_at = ReplyStatus.failed, None
                d.failure_reason = rejection_message(rv.google_reply_policy_violation)
        return
    if rv.google_reply_text is None:
        return
    for d in db.scalars(select(ReplyDraft).where(ReplyDraft.review_id == rv.id, ReplyDraft.status.in_([ReplyStatus.approved, ReplyStatus.failed]))):
        if d.body.strip() == rv.google_reply_text.strip():
            d.status = ReplyStatus.published
            d.published_at = rv.google_reply_at or utcnow()
            d.failure_reason = None


def sync_google_location(db: Session, gloc: GoogleLocation, provider=None, *, sleep=None) -> dict:
    """Sync one location. Never raises for expected Google errors; records them on the row."""
    conn = db.get(GoogleConnection, gloc.connection_id)
    result = {"new": 0, "updated": 0, "unchanged": 0, "status": "ok"}
    if not conn or conn.status != GoogleConnectionStatus.active or not gloc.selected:
        result["status"] = "skipped"
        return result
    from app.services import entitlements as ent

    if not ent.for_tenant(db, gloc.tenant_id).has("review_sync"):
        result["status"] = "skipped"  # subscription inactive / plan without sync: keep data, stop calling Google
        return result
    provider = provider or g.get_google_provider()
    gloc.last_sync_status = "running"
    db.commit()
    since = (gloc.last_synced_at - timedelta(days=1)) if gloc.last_synced_at else None
    try:
        token = get_access_token(db, conn, provider, gloc=gloc)
        page_token = None
        for _ in range(MAX_PAGES):
            page = with_backoff(lambda: provider.list_reviews(token, gloc.google_account_name, gloc.google_location_name, page_token), sleep=sleep)
            stop = False
            for gr in page.reviews:
                result[upsert_review(db, gloc, gr)] += 1
                latest = _parse(gr.updated_at) or _parse(gr.created_at)
                if since and latest and latest < since:
                    stop = True  # ordered by updateTime desc: everything after this is already synced
            db.commit()
            page_token = page.next_page_token
            if stop or not page_token:
                break
        gloc.last_synced_at = utcnow()
        gloc.last_sync_status, gloc.last_sync_error = "ok", None
        gloc.consecutive_failures, gloc.next_sync_after = 0, None
        note_api_access(conn, "approved")
    except g.GoogleApiNotApproved:
        db.rollback()
        gloc = db.get(GoogleLocation, gloc.id)
        note_api_access(db.get(GoogleConnection, gloc.connection_id), "awaiting_approval")
        _fail(gloc, "awaiting_approval", "Awaiting Google Business Profile API approval; will re-check automatically.", 6 * 3600)
        result["status"] = "awaiting_approval"
    except g.GoogleAuthRevoked as exc:
        db.rollback()
        gloc = db.get(GoogleLocation, gloc.id)
        code = getattr(exc, "code", None) if isinstance(exc, g.GoogleAgencyUnavailable) else None
        gloc.last_sync_status = "error"
        gloc.last_sync_error = (f"FlowQR could not confirm its access to this profile ({code}). Nothing was sent to Google and nothing was changed." if code
                                else "Google access revoked. Reconnect your Google account.")
        result["status"] = "revoked"
    except g.GoogleRateLimited as exc:
        db.rollback()
        gloc = db.get(GoogleLocation, gloc.id)
        _fail(gloc, "rate_limited", "Google rate limit reached; will retry automatically.", exc.retry_after)
        result["status"] = "rate_limited"
    except g.GoogleAPIError as exc:
        db.rollback()
        gloc = db.get(GoogleLocation, gloc.id)
        _fail(gloc, "error", str(exc), None)
        result["status"] = "error"
        if exc.status == 403 and conn.auth_mode == "agency_account":  # FlowQR may have been removed in Google: check once, and stop everything if so (no retry against that profile)
            db.commit()
            from app.services.google import agency

            if agency.on_permission_denied(db, conn.id) == "lost":
                result["status"] = "lost"
    except g.GoogleNotConfigured:
        raise  # the task reports "not_configured" (workers/tasks.py); that is a server setting, not a failure of this location
    except Exception:  # noqa: BLE001 - deliberately broad, and NOT silent: this is the last line before a row is left on "running" forever
        # Anything FlowQR did not anticipate (a review in a shape it cannot parse, a database error). The row was committed as "running" above, so without this it would stay that way, with no failure
        # counted and no back-off, and the same location would fail again every cycle without the owner or the operations page seeing it. It is logged with its traceback (error reporting picks it
        # up), shown as an error, counted, and backed off like any other failure. Other locations are separate jobs and are not affected.
        db.rollback()
        log.exception("Review sync failed unexpectedly for google location %s", gloc.id)
        gloc = db.get(GoogleLocation, gloc.id)
        _fail(gloc, "error", "FlowQR could not process Google's answer for this profile. It will try again automatically, and FlowQR has been told.", None)
        result["status"] = "error"
    db.commit()
    return result


def _fail(gloc: GoogleLocation, status: str, message: str, retry_after: int | None) -> None:
    gloc.consecutive_failures = (gloc.consecutive_failures or 0) + 1
    backoff = retry_after or min(300 * 2 ** (gloc.consecutive_failures - 1), 6 * 3600)  # 5m, 10m, 20m ... max 6h
    gloc.last_sync_status, gloc.last_sync_error = status, message[:500]
    gloc.next_sync_after = utcnow() + timedelta(seconds=backoff)


def due_locations(db: Session) -> list[GoogleLocation]:
    now = utcnow()
    cutoff = now - timedelta(minutes=settings.review_sync_interval_minutes)
    rows = db.scalars(
        select(GoogleLocation).join(GoogleConnection, GoogleConnection.id == GoogleLocation.connection_id).where(
            GoogleLocation.selected.is_(True), GoogleConnection.status == GoogleConnectionStatus.active)
    ).all()
    return [r for r in rows
            if (r.next_sync_after is None or r.next_sync_after <= now) and (r.last_synced_at is None or r.last_synced_at <= cutoff)]
