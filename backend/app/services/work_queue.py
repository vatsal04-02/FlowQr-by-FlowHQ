"""Platform-admin work queue: what needs a person across ALL businesses, from real records only.

  * failed Google actions: profile changes that failed, were blocked by a safety rule, or were invalidated because Google's value moved, and posts that failed to publish
  * pending approvals: changes and posts waiting for a business owner, oldest first, so stuck ones are visible
  * account requests: businesses that asked to be deleted (and any whose deletion is overdue), recent data exports, recent completed deletions

Read-only. Nothing here changes anything; it reads the same tables the owners' own screens read. Caller must be a platform admin (RLS bypass is set by the dependency)."""
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AuditLog, Subscription, Tenant
from app.models.agent import ScheduledPost
from app.models.autonomy import AgentAction
from app.models.base import utcnow
from app.models.business import GoogleLocation

FAILED_STATUSES = ("failed", "blocked", "invalidated")
RECENT_DAYS = 30


def _age_hours(when) -> float | None:
    return None if when is None else round((utcnow() - when).total_seconds() / 3600, 1)


def snapshot(db: Session, limit: int = 50) -> dict:
    now = utcnow()
    since = now - timedelta(days=RECENT_DAYS)

    failed_rows = db.execute(
        select(AgentAction, Tenant.name, GoogleLocation.title)
        .join(Tenant, Tenant.id == AgentAction.tenant_id).join(GoogleLocation, GoogleLocation.id == AgentAction.google_location_id)
        .where(AgentAction.status.in_(FAILED_STATUSES), AgentAction.updated_at >= since)
        .order_by(AgentAction.updated_at.desc()).limit(limit)).all()
    failed_counts = dict(db.execute(select(AgentAction.status, func.count()).where(AgentAction.status.in_(FAILED_STATUSES), AgentAction.updated_at >= since)
                                    .group_by(AgentAction.status)).all())
    failed_posts = db.execute(
        select(ScheduledPost, Tenant.name, GoogleLocation.title)
        .join(Tenant, Tenant.id == ScheduledPost.tenant_id).join(GoogleLocation, GoogleLocation.id == ScheduledPost.google_location_id)
        .where(ScheduledPost.status == "failed", ScheduledPost.updated_at >= since)
        .order_by(ScheduledPost.updated_at.desc()).limit(limit)).all()
    failed_posts_total = db.scalar(select(func.count()).select_from(ScheduledPost).where(ScheduledPost.status == "failed", ScheduledPost.updated_at >= since)) or 0

    pending_rows = db.execute(
        select(AgentAction, Tenant.name, GoogleLocation.title)
        .join(Tenant, Tenant.id == AgentAction.tenant_id).join(GoogleLocation, GoogleLocation.id == AgentAction.google_location_id)
        .where(AgentAction.status == "pending_approval")
        .order_by(AgentAction.created_at.asc()).limit(limit)).all()
    pending_total = db.scalar(select(func.count()).select_from(AgentAction).where(AgentAction.status == "pending_approval")) or 0
    posts_waiting = db.execute(select(func.count(), func.min(ScheduledPost.created_at)).where(ScheduledPost.status == "awaiting_approval")).one()

    deletions = db.execute(
        select(Tenant, Subscription.status).outerjoin(Subscription, Subscription.tenant_id == Tenant.id)
        .where(Tenant.deletion_scheduled_for.is_not(None)).order_by(Tenant.deletion_scheduled_for.asc()).limit(limit)).all()
    exports = db.execute(
        select(AuditLog, Tenant.name).outerjoin(Tenant, Tenant.id == AuditLog.tenant_id)
        .where(AuditLog.action == "account.export", AuditLog.created_at >= since).order_by(AuditLog.created_at.desc()).limit(limit)).all()
    deleted = db.execute(
        select(AuditLog).where(AuditLog.action == "account.deleted", AuditLog.created_at >= since).order_by(AuditLog.created_at.desc()).limit(limit)).scalars().all()

    return {
        "generated_at": now,
        "window_days": RECENT_DAYS,
        "failed": {
            "counts": {s: failed_counts.get(s, 0) for s in FAILED_STATUSES},
            "actions": [{
                "id": a.id, "tenant_id": a.tenant_id, "business": tname, "location": ltitle, "field": a.field_key, "action_type": a.action_type,
                "status": a.status, "attempts": a.attempts, "error": a.last_error, "policy_reasons": a.policy_reasons or [], "when": a.updated_at,
                "next_attempt_at": a.next_attempt_at} for a, tname, ltitle in failed_rows],
            "posts_total": failed_posts_total,
            "posts": [{"id": p.id, "tenant_id": p.tenant_id, "business": tname, "location": ltitle, "attempts": p.attempts, "error": p.failure_reason,
                       "scheduled_for": p.scheduled_for, "when": p.updated_at} for p, tname, ltitle in failed_posts],
        },
        "pending": {
            "actions_total": pending_total,
            "actions": [{
                "id": a.id, "tenant_id": a.tenant_id, "business": tname, "location": ltitle, "field": a.field_key, "action_type": a.action_type,
                "level": a.policy_level, "risk": a.risk_level, "waiting_hours": _age_hours(a.created_at), "expires_at": a.expires_at} for a, tname, ltitle in pending_rows],
            "posts_waiting": posts_waiting[0], "oldest_post_waiting_hours": _age_hours(posts_waiting[1]),
        },
        "account_requests": {
            "deletions_scheduled": [{
                "tenant_id": t.id, "business": t.name, "requested_at": t.deletion_requested_at, "scheduled_for": t.deletion_scheduled_for,
                "overdue": t.deletion_scheduled_for is not None and t.deletion_scheduled_for < now, "subscription_status": sub_status} for t, sub_status in deletions],
            "exports_recent": [{"tenant_id": e.tenant_id, "business": tname, "when": e.created_at, "files": (e.meta or {}).get("files"), "bytes": (e.meta or {}).get("bytes")}
                               for e, tname in exports],
            "deletions_completed": [{"when": d.created_at, "business_slug": (d.meta or {}).get("slug"), "google_grants_revoked": (d.meta or {}).get("google_grants_revoked"),
                                     "users_removed": (d.meta or {}).get("users_removed"), "cards_returned": (d.meta or {}).get("cards_returned")} for d in deleted],
        },
    }
