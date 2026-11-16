"""What a tenant may do right now, derived from its subscription row. Single source of truth for limits."""
import uuid
from dataclasses import dataclass, field
from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import BillingPlan, Invitation, Location, Membership, PromotionalGrant, Subscription
from app.models.base import utcnow

from app.services.plans import FEATURE_LABELS  # noqa: E402

ACTIVE_STATUSES = {"trialing", "active", "manual"}


def awaiting_first_charge(sub: Subscription | None, now=None) -> bool:
    """A free period has ended and the customer's authorised monthly payment is due or settling. Access continues for CASHFREE_CHARGE_SETTLEMENT_HOURS so a payment that is merely
    in flight never locks out someone who is paying. A failed charge ends this through the past_due path; a mandate that is not live (paused, cancelled, expired) never gets it."""
    if sub is None or sub.provider != "cashfree" or sub.authorization_status != "authorized" or sub.first_charge_at is None:
        return False
    now = now or utcnow()
    first = sub.first_charge_at if sub.first_charge_at.tzinfo else sub.first_charge_at.replace(tzinfo=now.tzinfo)
    return now < first + timedelta(hours=settings.cashfree_charge_settlement_hours)


@dataclass
class Entitlements:
    active: bool
    status: str
    plan: str
    max_locations: int
    monthly_ai_generations: int
    max_staff: int
    features: set[str] = field(default_factory=set)
    review_generations: int = 0  # monthly allowance for the review-writing assistant
    review_replies: int = 0  # monthly allowance for AI review replies: separate, never pooled
    limits: dict = field(default_factory=dict)  # other plan limits (geo-grid); a missing value means not configured
    promo: dict | None = None  # promotional access currently applied on top of the subscription (never counted as paid)
    reason: str | None = None  # why inactive
    trial_days_left: int | None = None
    grace_until: object | None = None

    def has(self, feature: str) -> bool:
        return self.active and feature in self.features


def compute(sub: Subscription | None, promo: tuple[PromotionalGrant, BillingPlan] | None = None) -> Entitlements:
    """Entitlements from the subscription row, plus (optionally) an ACTIVE promotional grant layered on top: the business gets the more generous of the two,
    and the grant is reported separately so it is never mistaken for a paid subscription."""
    e = _compute(sub)
    if promo is None:
        return e
    grant, plan = promo
    e.active, e.reason = True, None
    e.features = set(e.features) | set(plan.features or [])
    e.max_locations, e.max_staff = max(e.max_locations, plan.max_locations), max(e.max_staff, plan.max_staff)
    e.review_generations, e.review_replies = max(e.review_generations, plan.review_generations), max(e.review_replies, plan.review_replies)
    e.monthly_ai_generations = e.review_generations + e.review_replies
    if not e.limits.get("geo") or not any((e.limits.get("geo") or {}).values()):
        e.limits = dict(plan.limits or {})
    e.promo = {"plan": plan.code, "plan_name": plan.name, "ends_at": grant.ends_at, "kind": grant.kind}
    return e


def _compute(sub: Subscription | None) -> Entitlements:
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
            if not awaiting_first_charge(sub, now):
                active, status, reason = False, "expired", "trial_ended"
            trial_days_left = 0
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
        review_generations=sub.review_generations or 0, review_replies=sub.review_replies or 0, limits=dict(sub.limits or {}),
    )


def active_promo(db: Session, tenant_id: uuid.UUID) -> tuple[PromotionalGrant, BillingPlan] | None:
    now = utcnow()
    g = db.scalar(select(PromotionalGrant).where(PromotionalGrant.tenant_id == tenant_id, PromotionalGrant.status == "active", PromotionalGrant.starts_at <= now,
                                                 PromotionalGrant.ends_at > now).order_by(PromotionalGrant.ends_at.desc()).limit(1))
    plan = db.get(BillingPlan, g.plan) if g else None
    return (g, plan) if g and plan else None


def for_tenant(db: Session, tenant_id: uuid.UUID) -> Entitlements:
    return compute(db.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id)), active_promo(db, tenant_id))


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
            "message": f"{FEATURE_LABELS.get(feature, 'This feature')} isn't included in your current plan. Upgrade to use it.",
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
