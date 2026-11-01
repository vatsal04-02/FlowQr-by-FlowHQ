"""Subscription state machine driven by Razorpay (webhooks are the source of truth).

Local status is only ever changed from (a) verified webhooks or (b) data fetched directly from Razorpay's API
after signature verification. Nothing here marks a payment successful on the client's say-so.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import BillingPlan, CardOrder, Payment, Subscription, WebhookEvent
from app.models.base import utcnow
from app.services.audit import audit

log = logging.getLogger("flowqr.billing")


def ts(epoch: int | float | None) -> datetime | None:
    return datetime.fromtimestamp(epoch, tz=timezone.utc) if epoch else None


def apply_plan(sub: Subscription, plan: BillingPlan) -> None:
    sub.plan = plan.code
    sub.max_locations = plan.max_locations
    sub.monthly_ai_generations = plan.monthly_ai_generations
    sub.max_staff = plan.max_staff
    sub.features = list(plan.features or [])


def start_trial(db: Session, tenant_id: uuid.UUID) -> Subscription:
    plan = db.get(BillingPlan, settings.trial_plan)
    now = utcnow()
    sub = Subscription(tenant_id=tenant_id, plan="trial", status="trialing", currency="INR", source="trial",
                       trial_ends_at=now + timedelta(days=settings.trial_days),
                       current_period_end=now + timedelta(days=settings.trial_days))
    if plan:
        apply_plan(sub, plan)
        sub.plan = "trial"
    db.add(sub)
    return sub


def plan_by_razorpay_id(db: Session, rzp_plan_id: str | None) -> BillingPlan | None:
    if not rzp_plan_id:
        return None
    return db.scalar(select(BillingPlan).where(BillingPlan.razorpay_plan_id == rzp_plan_id))


def ensure_razorpay_plan(db: Session, client, plan: BillingPlan) -> str:
    """Create the plan at Razorpay lazily (idempotent: stored id is reused)."""
    if plan.razorpay_plan_id:
        return plan.razorpay_plan_id
    created = client.create_plan(name=f"FlowQR {plan.name}", amount_paise=plan.price_paise, currency=plan.currency, interval=plan.interval)
    plan.razorpay_plan_id = created["id"]
    db.flush()
    return plan.razorpay_plan_id


# Razorpay subscription.status -> local status
STATUS_MAP = {
    "created": None, "authenticated": None, "active": "active", "pending": "past_due", "halted": "halted",
    "cancelled": "canceled", "completed": "expired", "expired": "expired", "paused": "halted",
}


def sync_from_razorpay(db: Session, sub: Subscription, rz: dict, *, event_at: datetime | None = None) -> None:
    """Apply a Razorpay subscription entity (from webhook payload or API fetch) to our row."""
    if event_at and sub.last_event_at and event_at < sub.last_event_at:
        return  # stale/out-of-order event
    new_status = STATUS_MAP.get(rz.get("status"))
    plan = plan_by_razorpay_id(db, rz.get("plan_id"))
    if new_status == "active":
        sub.status, sub.source = "active", "razorpay"
        sub.past_due_since = None
        sub.trial_ends_at = None
        if plan:
            apply_plan(sub, plan)
            sub.pending_plan = None
    elif new_status == "past_due":
        sub.status = "past_due"
        sub.past_due_since = sub.past_due_since or (event_at or utcnow())
    elif new_status:
        sub.status = new_status
        if new_status == "canceled":
            sub.canceled_at = event_at or utcnow()
    elif rz.get("status") == "authenticated" and sub.status == "pending":
        pass  # mandate authorised; first charge still to come
    sub.current_period_start = ts(rz.get("current_start")) or sub.current_period_start
    sub.current_period_end = ts(rz.get("current_end")) or sub.current_period_end
    if rz.get("status") == "cancelled" or rz.get("ended_at"):
        sub.cancel_at_period_end = False
    if event_at:
        sub.last_event_at = event_at


def upsert_payment(db: Session, *, tenant_id: uuid.UUID, kind: str, entity: dict, card_order_id=None,
                   subscription_id: str | None = None) -> Payment:
    pid = entity.get("id")
    row = db.scalar(select(Payment).where(Payment.razorpay_payment_id == pid)) if pid else None
    status = {"captured": "captured", "authorized": "authorized", "failed": "failed", "refunded": "refunded", "created": "created"}.get(entity.get("status"), "created")
    if row is None:
        row = Payment(tenant_id=tenant_id, kind=kind, created_at=utcnow(), razorpay_payment_id=pid, amount_paise=entity.get("amount", 0),
                      currency=entity.get("currency", "INR"), status=status, meta={})
        db.add(row)
    elif row.status == "captured" and status != "refunded":
        return row  # never downgrade a captured payment
    row.status = status
    row.method = entity.get("method") or row.method
    row.razorpay_order_id = entity.get("order_id") or row.razorpay_order_id
    row.razorpay_invoice_id = entity.get("invoice_id") or row.razorpay_invoice_id
    row.razorpay_subscription_id = subscription_id or row.razorpay_subscription_id
    row.card_order_id = card_order_id or row.card_order_id
    row.error_code = entity.get("error_code") or row.error_code
    row.error_description = entity.get("error_description") or row.error_description
    if status == "captured" and not row.paid_at:
        row.paid_at = ts(entity.get("created_at")) or utcnow()
    db.flush()
    return row


def mark_card_order_paid(db: Session, order: CardOrder) -> None:
    if order.status in ("created", "failed"):
        order.status = "paid"


def process_webhook(db: Session, event: dict, event_id: str) -> str:
    """Returns 'processed' | 'ignored'. Raises on unexpected errors so the caller can 500 and Razorpay retries."""
    etype = event.get("event", "")
    payload = event.get("payload", {})
    sub_entity = (payload.get("subscription") or {}).get("entity")
    pay_entity = (payload.get("payment") or {}).get("entity")
    order_entity = (payload.get("order") or {}).get("entity")
    event_at = ts(event.get("created_at"))

    sub = None
    if sub_entity:
        sub = db.scalar(select(Subscription).where(Subscription.razorpay_subscription_id == sub_entity.get("id")))

    if etype.startswith("subscription."):
        if not sub:
            return "ignored"  # not one of ours / unknown subscription
        sync_from_razorpay(db, sub, sub_entity, event_at=event_at)
        if pay_entity and etype in ("subscription.charged",):
            upsert_payment(db, tenant_id=sub.tenant_id, kind="subscription", entity=pay_entity, subscription_id=sub.razorpay_subscription_id)
        audit(db, action=f"billing.{etype}", tenant_id=sub.tenant_id, entity_type="subscription", entity_id=sub.id,
              meta={"status": sub.status, "plan": sub.plan, "event_id": event_id})
        return "processed"

    if etype in ("payment.captured", "payment.failed", "payment.authorized", "order.paid"):
        entity = pay_entity or {}
        order_id = entity.get("order_id") or (order_entity or {}).get("id")
        order = db.scalar(select(CardOrder).where(CardOrder.razorpay_order_id == order_id)) if order_id else None
        if order:  # physical card purchase: tracked separately from subscriptions
            if entity:
                upsert_payment(db, tenant_id=order.tenant_id, kind="card_order", entity=entity, card_order_id=order.id)
            if etype in ("payment.captured", "order.paid"):
                mark_card_order_paid(db, order)
            audit(db, action=f"billing.card_order.{etype}", tenant_id=order.tenant_id, entity_type="card_order", entity_id=order.id,
                  meta={"event_id": event_id})
            return "processed"
        # subscription payment (failed renewal etc.): resolve tenant through the subscription id / existing payment
        sid = entity.get("subscription_id") or (sub.razorpay_subscription_id if sub else None)
        if not sid and entity.get("invoice_id"):
            existing = db.scalar(select(Payment).where(Payment.razorpay_invoice_id == entity["invoice_id"]))
            sid = existing.razorpay_subscription_id if existing else None
        owner = db.scalar(select(Subscription).where(Subscription.razorpay_subscription_id == sid)) if sid else None
        if owner and entity:
            upsert_payment(db, tenant_id=owner.tenant_id, kind="subscription", entity=entity, subscription_id=sid)
            if etype == "payment.failed":
                owner.status = "past_due" if owner.status in ("active", "past_due") else owner.status
                owner.past_due_since = owner.past_due_since or (event_at or utcnow())
            audit(db, action=f"billing.{etype}", tenant_id=owner.tenant_id, entity_type="subscription", entity_id=owner.id,
                  meta={"event_id": event_id})
            return "processed"
        return "ignored"
    return "ignored"


def record_event(db: Session, event_id: str, etype: str) -> WebhookEvent | None:
    """Insert the idempotency row. Returns None if this event id was already received (duplicate delivery)."""
    ev = WebhookEvent(provider="razorpay", event_id=event_id, event_type=etype, received_at=utcnow(), status="received")
    db.add(ev)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return None
    return ev


def refresh_statuses(db: Session) -> dict:
    """Daily housekeeping: expire trials and lapse past-due subscriptions after the grace period."""
    now = utcnow()
    expired = lapsed = 0
    for sub in db.scalars(select(Subscription).where(Subscription.status == "trialing", Subscription.trial_ends_at < now)):
        if not sub.razorpay_subscription_id:
            sub.status = "expired"
            expired += 1
    for sub in db.scalars(select(Subscription).where(Subscription.status == "past_due")):
        if sub.past_due_since and sub.past_due_since + timedelta(days=settings.past_due_grace_days) < now:
            sub.status = "halted"
            lapsed += 1
    db.commit()
    return {"expired_trials": expired, "lapsed_past_due": lapsed}
