"""Reply approval/publishing. A draft is 'published' ONLY after Google returns success."""
from sqlalchemy.orm import Session

from app.models import GoogleConnection, GoogleLocation, ReplyDraft, ReplyLog, ReplyStatus, Review
from app.models.base import utcnow
from app.services import google as g
from app.services.google.sync import rejection_message
from app.services.google.tokens import get_access_token, note_not_approved


def publish_draft(db: Session, draft: ReplyDraft, *, by_user, provider=None) -> ReplyDraft:
    if draft.status not in (ReplyStatus.approved, ReplyStatus.failed):
        raise ValueError("Only approved drafts can be published")
    if draft.status == ReplyStatus.failed and not draft.approved_by:
        raise ValueError("Draft was never approved by a person")
    review = db.get(Review, draft.review_id)
    gloc = db.get(GoogleLocation, review.google_location_id)
    conn = db.get(GoogleConnection, gloc.connection_id)
    draft.attempts += 1
    # Visible "publishing" state, committed BEFORE calling Google: other screens see it, a second click cannot start a second send
    # (only approved/failed drafts can be published), and a send interrupted by a crash is found and recovered by the retry job.
    # Google's reply call is an upsert (PUT), so recovering by sending again can never create a second reply.
    draft.status = ReplyStatus.publishing
    draft.failure_reason = None
    db.commit()
    http_status, error, ok = None, None, False
    try:
        provider = provider or g.get_google_provider()
        token = get_access_token(db, conn, provider)
        reply = provider.reply_to_review(token, gloc.google_account_name, gloc.google_location_name, review.external_id, draft.body) or {}
        http_status = 200
        review.google_reply_state, review.google_reply_policy_violation = reply.get("state"), reply.get("policy_violation")
        if reply.get("state") == "REJECTED":  # Google answered 200 but moderated the reply away: that is not a publish
            error = rejection_message(reply.get("policy_violation"))
        else:
            ok = True
    except g.GoogleApiNotApproved as exc:
        error, http_status = note_not_approved(conn, exc), exc.status
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
