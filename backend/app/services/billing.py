"""Subscription state machine driven by Razorpay (webhooks are the source of truth).

Local status is only ever changed from (a) verified webhooks or (b) data fetched directly from Razorpay's API
after signature verification. Nothing here marks a payment successful on the client's say-so.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import BillingPlan, CardOrder, Payment, PromotionalGrant, Subscription, SubscriptionEvent, WebhookEvent
from app.models.base import utcnow
from app.services import entitlements as ent
from app.services.audit import audit

log = logging.getLogger("flowqr.billing")


def ts(epoch: int | float | None) -> datetime | None:
    return datetime.fromtimestamp(epoch, tz=timezone.utc) if epoch else None


# ---------------------------------------------------------------------------------------------------------------------------------------------
# subscription history: every change of status or plan leaves an append-only row saying what, from what, to what, by whom
# ---------------------------------------------------------------------------------------------------------------------------------------------
def snapshot(sub: Subscription) -> tuple[str, str]:
    return (sub.status, sub.plan)


def log_event(db: Session, tenant_id: uuid.UUID, kind: str, *, source: str, from_status=None, to_status=None, from_plan=None, to_plan=None, ref: str | None = None,
              meta: dict | None = None) -> SubscriptionEvent:
    ev = SubscriptionEvent(tenant_id=tenant_id, created_at=utcnow(), kind=kind, from_status=from_status, to_status=to_status, from_plan=from_plan, to_plan=to_plan,
                           source=source, ref=(ref or None) and ref[:120], meta=meta or {})
    db.add(ev)
    return ev


def record_change(db: Session, sub: Subscription, before: tuple[str, str], *, source: str, ref: str | None = None, kind: str | None = None, meta: dict | None = None) -> SubscriptionEvent | None:
    """Log what changed between `before` (from `snapshot`) and now. Nothing changed and no explicit kind: nothing is logged."""
    b_status, b_plan = before
    if kind is None:
        if (sub.status, sub.plan) == before:
            return None
        if sub.plan != b_plan and sub.status == b_status:
            kind = "plan_changed"
        else:
            kind = {"active": "renewed" if b_status == "active" else "activated", "past_due": "past_due", "canceled": "canceled", "expired": "expired"}.get(sub.status, "status_changed")
    return log_event(db, sub.tenant_id, kind, source=source, from_status=b_status, to_status=sub.status, from_plan=b_plan, to_plan=sub.plan, ref=ref, meta=meta)


def apply_plan(sub: Subscription, plan: BillingPlan) -> None:
    sub.plan = plan.code
    sub.max_locations = plan.max_locations
    sub.monthly_ai_generations = plan.monthly_ai_generations
    sub.review_generations = plan.review_generations
    sub.review_replies = plan.review_replies
    sub.limits = dict(plan.limits or {})
    sub.max_staff = plan.max_staff
    sub.features = list(plan.features or [])


def start_trial(db: Session, tenant_id: uuid.UUID) -> Subscription:
    plan = db.get(BillingPlan, settings.trial_plan)
    now = utcnow()
    sub = Subscription(tenant_id=tenant_id, plan="trial", status="trialing", currency="INR", source="trial", trial_started_at=now,
                       trial_ends_at=now + timedelta(days=settings.trial_days),
                       current_period_end=now + timedelta(days=settings.trial_days))
    if plan:
        apply_plan(sub, plan)
        sub.plan = "trial"
    db.add(sub)
    log_event(db, tenant_id, "trial_started", source="system", to_status="trialing", to_plan="trial", meta={"days": settings.trial_days, "features_of": settings.trial_plan})
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
    if row is not None and row.tenant_id != tenant_id:
        # A payment id must belong to exactly one tenant. Never let an event for tenant B rewrite tenant A's payment.
        log.error("Payment %s already belongs to another tenant; ignoring conflicting event", pid)
        return row
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
        grant_card_promo(db, order)  # idempotent: one grant per order, however many times the payment event arrives


# ---------------------------------------------------------------------------------------------------------------------------------------------
# promotional access: the Growth month that comes with a physical card
# ---------------------------------------------------------------------------------------------------------------------------------------------
def card_offer_for(quantity: int) -> dict | None:
    return next((o for o in (settings.card_offers or []) if o.get("quantity") == quantity), None)


def grant_card_promo(db: Session, order: CardOrder, now: datetime | None = None) -> PromotionalGrant | None:
    """One month of the promo plan for a paid card order. NOT a subscription: it never changes the subscription row, never becomes MRR, and nothing is charged when it ends.
    Policy (owner decisions pending, see settings): at most `promo_max_grants_per_business` per business, starting when the payment is confirmed."""
    existing = db.scalar(select(PromotionalGrant).where(PromotionalGrant.card_order_id == order.id))
    if existing is not None:
        return existing
    prior = db.scalar(select(func.count()).select_from(PromotionalGrant).where(PromotionalGrant.tenant_id == order.tenant_id, PromotionalGrant.kind == "card_purchase",
                                                                              PromotionalGrant.status != "revoked")) or 0
    if prior >= settings.promo_max_grants_per_business:
        log_event(db, order.tenant_id, "promo_denied", source="promo", ref=str(order.id), meta={"reason": "this business already received its card-purchase month"})
        return None
    now = now or utcnow()
    g = PromotionalGrant(tenant_id=order.tenant_id, kind="card_purchase", plan=settings.promo_card_plan, status="active", starts_at=now,
                         ends_at=now + timedelta(days=settings.promo_card_days), card_order_id=order.id, created_at=now, note=f"Included with card order {order.id}")
    db.add(g)
    db.flush()
    log_event(db, order.tenant_id, "promo_granted", source="promo", to_plan=g.plan, ref=str(order.id), meta={"ends_at": g.ends_at.isoformat(), "days": settings.promo_card_days})
    audit(db, action="billing.promo_granted", tenant_id=order.tenant_id, entity_type="promotional_grant", entity_id=g.id, meta={"plan": g.plan, "card_order": str(order.id)})
    return g


def end_expired_grants(db: Session, now: datetime | None = None) -> int:
    """Mark grants whose month is over as ended (entitlements already stop honouring them at ends_at; this is the record). Nothing is charged."""
    now = now or utcnow()
    n = 0
    for g in db.scalars(select(PromotionalGrant).where(PromotionalGrant.status == "active", PromotionalGrant.ends_at <= now)):
        g.status = "ended"
        log_event(db, g.tenant_id, "promo_ended", source="system", from_plan=g.plan, ref=str(g.card_order_id) if g.card_order_id else None)
        n += 1
    return n


def process_refund(db: Session, event: dict, event_id: str) -> str:
    """A refund is applied to the payment it belongs to. Policy: a refund NEVER deletes data and never cancels a subscription by itself (that is a person's decision,
    shown in the admin payments view); a refunded CARD order ends the promotional month it carried."""
    payload = event.get("payload", {})
    ref_e = (payload.get("refund") or {}).get("entity") or {}
    pay_e = (payload.get("payment") or {}).get("entity") or {}
    payment_id = ref_e.get("payment_id") or pay_e.get("id")
    pay = db.scalar(select(Payment).where(Payment.razorpay_payment_id == payment_id)) if payment_id else None
    if pay is None:
        return "ignored"
    refunds = dict((pay.meta or {}).get("refunds") or {})
    if ref_e.get("id") and ref_e["id"] in refunds:
        return "processed"  # this refund was already applied (a redelivery): nothing changes, nothing is logged twice
    if ref_e.get("id"):
        refunds[ref_e["id"]] = int(ref_e.get("amount") or 0)
    elif pay_e.get("amount_refunded"):
        refunds["payment"] = int(pay_e["amount_refunded"])
    pay.meta = {**(pay.meta or {}), "refunds": refunds}
    total = sum(refunds.values())
    if total >= pay.amount_paise > 0:
        pay.status = "refunded"
    log_event(db, pay.tenant_id, "refunded", source="webhook", ref=event_id, meta={"payment": payment_id, "refunded_paise": total, "kind": pay.kind, "full": pay.status == "refunded"})
    audit(db, action="billing.refund", tenant_id=pay.tenant_id, entity_type="payment", entity_id=pay.id, meta={"refunded_paise": total, "event_id": event_id})
    if pay.status == "refunded" and pay.card_order_id:
        order = db.get(CardOrder, pay.card_order_id)
        if order is not None:
            order.status = "refunded"
            g = db.scalar(select(PromotionalGrant).where(PromotionalGrant.card_order_id == order.id))
            if g is not None and g.status == "active":
                g.status, g.ends_at = "revoked", min(g.ends_at, utcnow())
                log_event(db, g.tenant_id, "promo_revoked", source="webhook", from_plan=g.plan, ref=event_id, meta={"reason": "the card order was refunded"})
    return "processed"


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
        before = snapshot(sub)
        sync_from_razorpay(db, sub, sub_entity, event_at=event_at)
        record_change(db, sub, before, source="webhook", ref=event_id, meta={"event": etype})
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
                before = snapshot(owner)
                owner.status = "past_due" if owner.status in ("active", "past_due") else owner.status
                owner.past_due_since = owner.past_due_since or (event_at or utcnow())
                record_change(db, owner, before, source="webhook", ref=event_id, kind="payment_failed", meta={"payment": entity.get("id"), "reason": entity.get("error_code")})
            audit(db, action=f"billing.{etype}", tenant_id=owner.tenant_id, entity_type="subscription", entity_id=owner.id,
                  meta={"event_id": event_id})
            return "processed"
        return "ignored"
    if etype in ("refund.processed", "refund.created", "payment.refunded"):
        return process_refund(db, event, event_id)
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
        if not sub.razorpay_subscription_id and not ent.awaiting_first_charge(sub, now):  # a Cashfree mandate whose first charge is settling is not an expired trial
            before = snapshot(sub)
            sub.status = "expired"
            record_change(db, sub, before, source="system", meta={"reason": "trial ended"})
            expired += 1
    for sub in db.scalars(select(Subscription).where(Subscription.status == "past_due")):
        if sub.past_due_since and sub.past_due_since + timedelta(days=settings.past_due_grace_days) < now:
            before = snapshot(sub)
            sub.status = "halted"
            record_change(db, sub, before, source="system", meta={"reason": f"payment still failing after the {settings.past_due_grace_days}-day grace period"})
            lapsed += 1
    promos = end_expired_grants(db, now)
    db.commit()
    return {"expired_trials": expired, "lapsed_past_due": lapsed, "promos_ended": promos}
