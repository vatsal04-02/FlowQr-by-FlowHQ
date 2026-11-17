"""Prepaid plans: buy 1, 3, 6 or 12 months of a plan with ONE Cashfree Payment Gateway payment. No subscription, no mandate, no AutoPay, no Rs 1 authorisation, nothing recurring.

The rules this module exists to keep:
  * The SERVER prices the order, from services/plans.py (TERM_PRICES_PAISE). The browser sends a plan, a number of months and a phone number; never an amount.
  * Access is granted ONLY when Cashfree itself (an authenticated call from here) reports the order PAID, for exactly the amount and currency FlowQR stored. The browser's return page, a webhook body and
    anything else are hints that make us ask; none of them is believed. A wrong amount grants nothing and is flagged.
  * Granting is idempotent and serialised: the order row is locked, `activated_at` is set once, and the term is written once however many times the return page, the webhook and the hourly
    reconcile all arrive. Money is never taken twice for one grant, and a payment is never left without its grant.
  * A failed, abandoned, pending or expired payment changes nothing about the customer's access.
  * Access ends BY THE CLOCK: entitlements.py treats a prepaid term as inactive once `current_period_end` passes, whether or not any job has run.
  * Nothing here logs or stores a card number, a UPI id, a phone number, a payment session or a secret. The phone goes to Cashfree (which requires it) and nowhere else."""
from __future__ import annotations

import calendar
import logging
import re
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import BillingPlan, Payment, PrepaidOrder, PrepaidPriceOverride, Subscription, Tenant, User, WebhookEvent
from app.models.base import utcnow
from app.services import billing as billing_svc
from app.services import cashfree as cf
from app.services import plans as plans_svc
from app.services.audit import audit
from app.services.billing_cashfree import _owners
from app.services.mailer import send_email

log = logging.getLogger("flowqr.prepaid")
PROVIDER = "cashfree_pg"
OPEN_STATES = ("created", "failed")  # an order that may still turn out to be paid


class PrepaidError(Exception):
    """A refusal with a code the app can show. `status` is the HTTP status the API answers with."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def add_months(dt: datetime, months: int) -> datetime:
    """Calendar months, clamped to the end of a short month (31 Jan + 1 month = 28/29 Feb)."""
    idx = dt.month - 1 + months
    year, month = dt.year + idx // 12, idx % 12 + 1
    return dt.replace(year=year, month=month, day=min(dt.day, calendar.monthrange(year, month)[1]))


def clean_phone(raw: str | None) -> str:
    """Cashfree requires the payer's phone. An Indian mobile number: 10 digits starting 6-9, with an optional +91 or 0."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not re.fullmatch(r"[6-9]\d{9}", digits):
        raise PrepaidError(422, "invalid_phone", "Enter a 10-digit Indian mobile number.")
    return digits


def price_for(plan_code: str, months: int) -> int:
    paise = (plans_svc.TERM_PRICES_PAISE.get(plan_code) or {}).get(months)
    if not paise:
        raise PrepaidError(422, "unknown_term", "That plan and duration is not available.")
    return paise


def active_override(db: Session, tenant_id: uuid.UUID, plan_code: str, months: int, now: datetime, *, lock: bool = False) -> PrepaidPriceOverride | None:
    """The temporary price this business may use for this plan and term right now, or None. It must be unexpired, unrevoked and unused. It can only ever LOWER the listed price."""
    q = select(PrepaidPriceOverride).where(PrepaidPriceOverride.tenant_id == tenant_id, PrepaidPriceOverride.plan_code == plan_code, PrepaidPriceOverride.months == months,
                                           PrepaidPriceOverride.revoked_at.is_(None), PrepaidPriceOverride.used_order_id.is_(None), PrepaidPriceOverride.expires_at > now).order_by(PrepaidPriceOverride.created_at.desc()).limit(1)
    ov = db.scalar(q.with_for_update() if lock else q)
    if ov is not None and not (0 < ov.amount_paise < price_for(plan_code, months)):
        return None  # a stale or wrong row (the list price fell below it): never charge more than the list price
    return ov


def offers_for(db: Session, tenant_id: uuid.UUID, now: datetime | None = None) -> list[dict]:
    """What the pricing screen may show THIS business as a temporary price. Informational only: the server decides the amount again when the order is created."""
    now = now or utcnow()
    rows = db.scalars(select(PrepaidPriceOverride).where(PrepaidPriceOverride.tenant_id == tenant_id, PrepaidPriceOverride.revoked_at.is_(None), PrepaidPriceOverride.used_order_id.is_(None),
                                                         PrepaidPriceOverride.expires_at > now)).all()
    return [{"plan": o.plan_code, "months": o.months, "amount_paise": o.amount_paise, "list_price_paise": o.list_price_paise, "label": o.label, "expires_at": o.expires_at}
            for o in rows if active_override(db, tenant_id, o.plan_code, o.months, now) is not None]


def blocked_reason(sub: Subscription | None, now: datetime) -> PrepaidError | None:
    """Why this business cannot start a prepaid purchase right now (None = it can)."""
    if sub is None:
        return None
    live_rzp = bool(sub.razorpay_subscription_id) and sub.status in ("active", "past_due", "pending")
    live_cf = bool(sub.cashfree_subscription_id) and sub.authorization_status in ("authorized", "bank_pending") and sub.status in ("active", "past_due", "trialing")
    if live_rzp or live_cf:
        return PrepaidError(409, "subscription_active", "You already have a monthly payment set up. Contact support if you want to move to a prepaid plan.")
    if sub.provider == "prepaid" and sub.status == "active" and sub.current_period_end and sub.current_period_end > now:
        return PrepaidError(409, "term_running", f"Your plan is active until {sub.current_period_end:%d %b %Y}. You can buy another term when it ends.")
    return None


# ------------------------------------------------------------------------------------------------------------------------------------ creating the order
def create_order(db: Session, client: cf.CashfreeClient, *, sub: Subscription | None, tenant: Tenant, user: User, plan_code: str, months: int, phone: str | None,
                 now: datetime | None = None) -> dict:
    """Prices the order on the server, records it, asks Cashfree to create it and returns what the browser needs to open Cashfree's payment page. Nothing is granted here."""
    now = now or utcnow()
    if not settings.prepaid_configured:
        raise PrepaidError(503, "checkout_closed", "Online payment for prepaid plans is not open yet.")
    plan = db.get(BillingPlan, plan_code)
    if plan is None or not plan.is_active:
        raise PrepaidError(404, "unknown_plan", "Unknown plan.")
    list_price = price_for(plan_code, months)
    ov = active_override(db, tenant.id, plan_code, months, now)  # the SERVER decides: a temporary price exists only for the business it was created for, once, until it expires
    amount = ov.amount_paise if ov else list_price
    blocked = blocked_reason(sub, now)
    if blocked:
        raise blocked
    digits = clean_phone(phone)
    order = PrepaidOrder(tenant_id=tenant.id, created_by=user.id, plan_code=plan_code, months=months, amount_paise=amount, currency="INR", status="created", order_id="fqp_" + uuid.uuid4().hex[:24],
                         list_price_paise=list_price, override_id=ov.id if ov else None)
    db.add(order)
    db.flush()
    base = settings.frontend_url.rstrip("/")
    notify = settings.prepaid_notify_url or None
    try:
        res = client.create_order(order_id=order.order_id, amount_paise=amount, customer_id="u_" + user.id.hex, customer=cf.Customer(name=(user.full_name or "FlowQR customer")[:100], email=user.email, phone=digits),
                                  return_url=f"{base}/settings/billing/pay-return?order_id={order.order_id}", notify_url=notify, expires_at=now + timedelta(minutes=settings.prepaid_order_minutes),
                                  note=f"FlowQR {plan.name} prepaid {months} month{'s' if months != 1 else ''}", idempotency_key=str(uuid.uuid5(uuid.NAMESPACE_URL, "flowqr-prepaid:" + order.order_id)))
    except cf.CashfreeError as exc:
        db.rollback()
        log.warning("Cashfree order creation failed: %s %s", exc.status, exc.code)
        raise PrepaidError(502, "provider_error", "The payment provider could not start this payment. Nothing was charged. Please try again.") from exc
    if not res.session_id or (res.amount_paise is not None and res.amount_paise != amount):
        db.rollback()
        log.error("Cashfree order answer unusable (session=%s amount_ok=%s)", bool(res.session_id), res.amount_paise == amount)
        raise PrepaidError(502, "provider_error", "The payment provider could not start this payment. Nothing was charged. Please try again.")
    order.cf_order_id = res.cf_order_id
    audit(db, action="billing.prepaid_order_created", tenant_id=tenant.id, user_id=user.id, entity_type="prepaid_order", entity_id=order.id,
          meta={"plan": plan_code, "months": months, "amount_paise": amount, "list_price_paise": list_price, "override_id": str(ov.id) if ov else None, "order_id": order.order_id})
    return {"order_id": order.order_id, "payment_session_id": res.session_id, "environment": "production" if (settings.cashfree_env or "").lower() == "production" else "sandbox",
            "plan": plan_code, "plan_name": plan.name, "months": months, "amount_paise": amount, "list_price_paise": list_price, "override": bool(ov)}


# ------------------------------------------------------------------------------------------------------------------------------------ the one place a term is granted
def activate(db: Session, order: PrepaidOrder, *, now: datetime, source: str) -> bool:
    """Write the paid term onto the business's subscription. Idempotent: returns False (and changes nothing) if this order was already activated."""
    if order.activated_at is not None:
        return False
    sub = db.scalar(select(Subscription).where(Subscription.tenant_id == order.tenant_id).with_for_update())
    plan = db.get(BillingPlan, order.plan_code)
    if sub is None or plan is None:
        raise PrepaidError(500, "activation_failed", "The payment is recorded but the plan could not be applied. Support has been notified.")
    before = billing_svc.snapshot(sub)
    running = sub.provider == "prepaid" and sub.status == "active" and sub.current_period_end is not None and sub.current_period_end > now
    if running and sub.plan == order.plan_code:  # a second paid order for the plan that is already running: the time is ADDED, never lost
        start, end = sub.current_period_start or now, add_months(sub.current_period_end, order.months)
    elif running:  # a different plan paid while another term runs (only possible through a race): the new plan starts now and the unused time is carried over in full
        start, end = now, add_months(now, order.months) + (sub.current_period_end - now)
    else:
        start, end = now, add_months(now, order.months)
    billing_svc.apply_plan(sub, plan)
    sub.status, sub.source, sub.provider = "active", "prepaid", "prepaid"
    sub.current_period_start, sub.current_period_end = start, end
    sub.cancel_at_period_end, sub.canceled_at, sub.past_due_since, sub.pending_plan = False, None, None, None
    order.activated_at, order.period_start, order.period_end = now, start, end
    db.add(Payment(tenant_id=order.tenant_id, kind="subscription", status="captured", amount_paise=order.amount_paise, currency=order.currency, provider="cashfree",
                   cashfree_cf_payment_id=order.cf_payment_id, payment_type="PREPAID", period_start=start, period_end=end, method=order.payment_method, paid_at=order.paid_at or now,
                   created_at=now, meta={"order_id": order.order_id, "plan": order.plan_code, "months": order.months}))
    billing_svc.record_change(db, sub, before, source="prepaid", ref=order.order_id, kind="activated", meta={"order_id": order.order_id, "months": order.months, "ends_at": end.isoformat(), "via": source})
    audit(db, action="billing.prepaid_activated", tenant_id=order.tenant_id, entity_type="prepaid_order", entity_id=order.id,
          meta={"plan": order.plan_code, "months": order.months, "ends_at": end.isoformat(), "via": source})
    for u in _owners(db, order.tenant_id):
        send_email(u.email, "Your FlowQR plan is active",
                   f"Your payment of Rs {order.amount_paise / 100:,.0f} was received and your {plan.name} plan is active for {order.months} month{'s' if order.months != 1 else ''}, until {end:%d %b %Y}.\n\n"
                   "It will not renew by itself and nothing more will be charged. Your bank or UPI app shows the payment, and Billing > Payments lists it.\n\n"
                   f"{settings.frontend_url.rstrip('/')}/settings/billing")
    return True


# ------------------------------------------------------------------------------------------------------------------------------------ reading the truth from Cashfree
def apply_remote(db: Session, client: cf.CashfreeClient, order_id: uuid.UUID, *, source: str, now: datetime | None = None) -> dict:
    """Ask Cashfree what really happened to this order and apply it. Safe to call any number of times, from any path, in any order."""
    now = now or utcnow()
    order = db.scalar(select(PrepaidOrder).where(PrepaidOrder.id == order_id).with_for_update())
    if order is None:
        raise PrepaidError(404, "order_not_found", "Order not found.")
    if order.activated_at is not None:
        return _state(order)
    remote = client.fetch_order(order.order_id)
    if remote.order_id and remote.order_id != order.order_id:
        log.error("Cashfree answered a different order id for %s", order.order_id)
        raise PrepaidError(502, "provider_error", "The payment provider returned an unexpected answer.")
    payments = client.list_order_payments(order.order_id)
    ok = next((p for p in payments if p.status == "SUCCESS"), None)
    if remote.status == "PAID":
        if remote.amount_paise != order.amount_paise or (remote.currency or "INR") != order.currency or (ok is not None and ok.amount_paise != order.amount_paise):
            order.status, order.failure_reason = "mismatch", "amount_mismatch"
            audit(db, action="billing.prepaid_amount_mismatch", tenant_id=order.tenant_id, entity_type="prepaid_order", entity_id=order.id,
                  meta={"expected_paise": order.amount_paise, "reported_paise": remote.amount_paise, "order_id": order.order_id})
            log.error("Prepaid order %s paid with a different amount: nothing granted", order.order_id)
            return _state(order)
        if order.override_id is not None:  # a temporary price grants ONE term: a second paid order under the same override is a payment for support to look at, not another grant
            ov = db.scalar(select(PrepaidPriceOverride).where(PrepaidPriceOverride.id == order.override_id).with_for_update())
            if ov is not None and ov.used_order_id not in (None, order.id):
                order.status, order.failure_reason = "mismatch", "override_already_used"
                audit(db, action="billing.prepaid_override_reused", tenant_id=order.tenant_id, entity_type="prepaid_order", entity_id=order.id, meta={"override_id": str(ov.id), "order_id": order.order_id})
                log.error("Prepaid order %s was paid under an override that was already used: nothing granted", order.order_id)
                return _state(order)
        order.status, order.failure_reason = "paid", None
        order.paid_at = (ok.paid_at if ok and ok.paid_at else None) or now
        if ok:
            order.cf_payment_id, order.payment_method = ok.cf_payment_id[:32] or None, (ok.method or None) and ok.method[:24]
        if activate(db, order, now=now, source=source) and order.override_id is not None:
            ov = db.get(PrepaidPriceOverride, order.override_id)
            if ov is not None:
                ov.used_order_id, ov.used_at = order.id, now  # consumed by the first PAID order that used it
        return _state(order)
    if remote.status in ("EXPIRED", "TERMINATED", "TERMINATION_REQUESTED"):
        if order.status != "paid":
            order.status = "expired"
        return _state(order)
    bad = next((p for p in sorted(payments, key=lambda p: p.paid_at or now, reverse=True) if p.status in ("FAILED", "USER_DROPPED", "CANCELLED", "VOID")), None)
    pending = any(p.status == "PENDING" for p in payments)
    if bad is not None and not pending:
        order.status, order.failure_reason = "failed", ((bad.failure_reason or bad.status.replace("_", " ").lower())[:300])
    return _state(order, pending=pending)


def _state(order: PrepaidOrder, *, pending: bool = False) -> dict:
    """What the return page may show. `state` is one of: paid, pending (money may be on its way), failed (try again), expired, mismatch (support), open (nothing attempted yet)."""
    if order.activated_at is not None:
        state = "paid"
    elif order.status == "mismatch":
        state = "mismatch"
    elif order.status == "expired":
        state = "expired"
    elif pending:
        state = "pending"
    elif order.status == "failed":
        state = "failed"
    else:
        state = "open"
    return {"state": state, "order_id": order.order_id, "plan": order.plan_code, "months": order.months, "amount_paise": order.amount_paise,
            "ends_at": order.period_end if order.activated_at else None, "failure_reason": order.failure_reason if state == "failed" else None}


def verify(db: Session, client: cf.CashfreeClient, *, tenant_id: uuid.UUID, order_id: str) -> dict:
    """The return page's question. Tenant-scoped: another business's order id answers 'not found'. Reads NOTHING the browser claims about the payment."""
    order = db.scalar(select(PrepaidOrder).where(PrepaidOrder.order_id == order_id, PrepaidOrder.tenant_id == tenant_id))
    if order is None:
        raise PrepaidError(404, "order_not_found", "Order not found.")
    try:
        return apply_remote(db, client, order.id, source="return")
    except cf.CashfreeError as exc:
        log.warning("Cashfree order read failed on return: %s %s", exc.status, exc.code)
        out = _state(order)
        out["state"] = "pending" if out["state"] == "open" else out["state"]
        out["unconfirmed"] = True  # we could not reach Cashfree: say so, grant nothing, and let the webhook and the hourly check finish the job
        return out


# ------------------------------------------------------------------------------------------------------------------------------------ webhook
def record_pg_event(db: Session, env: cf.PgWebhook) -> tuple[WebhookEvent | None, bool]:
    row = WebhookEvent(provider=PROVIDER, event_id=env.dedupe_key, event_type=env.type[:64], received_at=utcnow(), status="received", subscription_ref=env.order_id,
                       payment_ref=(env.cf_payment_id or None), payload_hash=env.payload_hash, attempts=0)
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
        return row, True
    except IntegrityError:
        return db.scalar(select(WebhookEvent).where(WebhookEvent.event_id == env.dedupe_key)), False


def process_pg_event(db: Session, client: cf.CashfreeClient, row: WebhookEvent, env: cf.PgWebhook) -> str:
    row.attempts = (row.attempts or 0) + 1
    try:
        order = db.scalar(select(PrepaidOrder).where(PrepaidOrder.order_id == env.order_id)) if env.order_id else None  # OUR order id only: nothing else in the payload picks a tenant
        if order is None:
            row.status, row.processed_at, row.last_error = "ignored", utcnow(), None
            return "ignored"
        apply_remote(db, client, order.id, source="webhook")
        row.status, row.processed_at, row.last_error = "processed", utcnow(), None
        return "processed"
    except cf.CashfreeError as exc:
        row.status, row.last_error = "failed", f"provider {exc.status} {exc.code}"[:300]
        raise


# ------------------------------------------------------------------------------------------------------------------------------------ hourly safety net
def reconcile(db: Session, client: cf.CashfreeClient, *, now: datetime | None = None, limit: int = 100) -> dict:
    """A webhook can be lost and a customer can close the tab: read every recent order that is not settled and apply the truth. Never touches an order older than three days."""
    now = now or utcnow()
    rows = db.scalars(select(PrepaidOrder).where(PrepaidOrder.status.in_(OPEN_STATES), PrepaidOrder.activated_at.is_(None), PrepaidOrder.created_at > now - timedelta(days=3),
                                                 PrepaidOrder.created_at < now - timedelta(minutes=2)).order_by(PrepaidOrder.created_at).limit(limit)).all()
    out = {"checked": 0, "paid": 0, "errors": 0}
    for o in rows:
        try:
            with db.begin_nested():
                r = apply_remote(db, client, o.id, source="reconcile", now=now)
            out["checked"] += 1
            out["paid"] += 1 if r["state"] == "paid" else 0
        except Exception:  # one bad order never stops the rest
            out["errors"] += 1
            log.exception("prepaid reconcile failed for an order")
    db.commit()
    return out
