"""What a tenant may do right now, derived from its subscription row. Single source of truth for limits."""
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Invitation, Location, Membership, Subscription
from app.models.base import utcnow

ACTIVE_STATUSES = {"trialing", "active", "manual"}


@dataclass
class Entitlements:
    active: bool
    status: str
    plan: str
    max_locations: int
    monthly_ai_generations: int
    max_staff: int
    features: set[str] = field(default_factory=set)
    reason: str | None = None  # why inactive
    trial_days_left: int | None = None
    grace_until: object | None = None

    def has(self, feature: str) -> bool:
        return self.active and feature in self.features


def compute(sub: Subscription | None) -> Entitlements:
    if sub is None:
        return Entitlements(False, "none", "none", 0, 0, 0, set(), "no_subscription")
    now = utcnow()
    status = sub.status
    active = status in ACTIVE_STATUSES
    reason = None
    grace_until = None
    trial_days_left = None
    if status == "trialing":
        if sub.trial_ends_at and sub.trial_ends_at <= now:
            active, status, reason = False, "expired", "trial_ended"
        elif sub.trial_ends_at:
            trial_days_left = max(0, (sub.trial_ends_at - now).days)
    elif status == "past_due":
        since = sub.past_due_since or now
        grace_until = since + timedelta(days=settings.past_due_grace_days)
        active = now < grace_until
        reason = None if active else "payment_failed"
    elif status in ("halted", "expired", "canceled", "cancelled"):
        # cancel_at_period_end keeps access until the paid period ends
        if status in ("canceled", "cancelled") and sub.current_period_end and sub.current_period_end > now:
            active = True
        else:
            reason = {"halted": "payment_failed", "expired": "trial_ended"}.get(status, "canceled")
    elif status == "pending":
        reason = "payment_pending"
    return Entitlements(
        active=active, status=status, plan=sub.plan, max_locations=sub.max_locations,
        monthly_ai_generations=sub.monthly_ai_generations, max_staff=sub.max_staff, features=set(sub.features or []),
        reason=reason, trial_days_left=trial_days_left, grace_until=grace_until,
    )


def for_tenant(db: Session, tenant_id: uuid.UUID) -> Entitlements:
    return compute(db.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id)))


def require_active(db: Session, tenant_id: uuid.UUID) -> Entitlements:
    ent = for_tenant(db, tenant_id)
    if not ent.active:
        raise HTTPException(status_code=402, detail={
            "code": "subscription_inactive", "reason": ent.reason,
            "message": "Your FlowQR subscription isn't active. Choose a plan to continue.",
        })
    return ent


def require_feature(db: Session, tenant_id: uuid.UUID, feature: str) -> Entitlements:
    ent = require_active(db, tenant_id)
    if feature not in ent.features:
        raise HTTPException(status_code=402, detail={
            "code": "plan_upgrade_required", "feature": feature,
            "message": "This feature isn't included in your current plan. Upgrade to use it.",
        })
    return ent


def seats_used(db: Session, tenant_id: uuid.UUID) -> int:
    members = db.scalar(select(func.count()).select_from(Membership).where(Membership.tenant_id == tenant_id)) or 0
    pending = db.scalar(select(func.count()).select_from(Invitation).where(
        Invitation.tenant_id == tenant_id, Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None),
        Invitation.expires_at > utcnow())) or 0
    return members + pending


def locations_used(db: Session, tenant_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(Location).where(Location.tenant_id == tenant_id, Location.is_active.is_(True))) or 0
