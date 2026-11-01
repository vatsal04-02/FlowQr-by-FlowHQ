"""Reply approval/publishing. A draft is 'published' ONLY after Google returns success."""
from sqlalchemy.orm import Session

from app.models import GoogleConnection, GoogleLocation, ReplyDraft, ReplyLog, ReplyStatus, Review
from app.models.base import utcnow
from app.services import google as g
from app.services.google.tokens import get_access_token


def publish_draft(db: Session, draft: ReplyDraft, *, by_user, provider=None) -> ReplyDraft:
    if draft.status not in (ReplyStatus.approved, ReplyStatus.failed):
        raise ValueError("Only approved drafts can be published")
    if draft.status == ReplyStatus.failed and not draft.approved_by:
        raise ValueError("Draft was never approved by a person")
    review = db.get(Review, draft.review_id)
    gloc = db.get(GoogleLocation, review.google_location_id)
    conn = db.get(GoogleConnection, gloc.connection_id)
    draft.attempts += 1
    http_status, error, ok = None, None, False
    try:
        provider = provider or g.get_google_provider()
        token = get_access_token(db, conn, provider)
        provider.reply_to_review(token, gloc.google_account_name, gloc.google_location_name, review.external_id, draft.body)
        ok, http_status = True, 200
    except g.GoogleAuthRevoked:
        error = "Google access was revoked. Reconnect your Google account and retry."
    except g.GoogleRateLimited:
        error, http_status = "Google rate limit reached. Try again in a few minutes.", 429
    except g.GoogleAPIError as exc:
        error, http_status = str(exc), exc.status
    except g.GoogleNotConfigured:
        error = "Google integration is not configured."
    db.add(ReplyLog(tenant_id=draft.tenant_id, review_id=review.id, draft_id=draft.id, user_id=getattr(by_user, "id", by_user),
                    action="publish_attempt", success=ok, http_status=http_status, error=error, created_at=utcnow()))
    if ok:
        draft.status = ReplyStatus.published
        draft.published_at = utcnow()
        draft.failure_reason = None
        review.google_reply_text = draft.body
        review.google_reply_at = draft.published_at
    else:
        draft.status = ReplyStatus.failed
        draft.failure_reason = error
    db.commit()
    return draft
