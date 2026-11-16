"""Subscription lifecycle on Cashfree. Cashfree OWNS collection; FlowQR owns entitlement dates and every access decision.

Rules this module is built on (each has a test in tests/test_cashfree_billing.py):
  * Cashfree's ACTIVE means "the mandate is registered", NOT "money was collected". A business becomes paid (`active`) only when a monthly CHARGE payment is verified as SUCCESS.
    The refundable authorisation (payment_type AUTH, stored with kind `sub_auth`) is never revenue and never starts a billing period.
  * A webhook is a HINT. The tenant is found from OUR subscription id only, then the subscription and its payments are read afresh from Cashfree and applied. So a forged or
    replayed or out-of-order event cannot move state anywhere the provider's own answer does not already say.
  * Every apply is idempotent: payments are upserted by their id, a payment is "newly captured" only once, and state is derived, never accumulated.
  * Nothing here creates a charge. The one call that can move money is Cashfree's own documented RETRY of a failed card charge, limited to Cashfree's 3 per cycle."""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import BillingPlan, Membership, Payment, Role, Subscription, SubscriptionEvent, Tenant, User, WebhookEvent
from app.models.base import utcnow
from app.services import billing as svc
from app.services import cashfree as cf
from app.services.audit import audit
from app.services.mailer import send_email

log = logging.getLogger("flowqr.billing.cashfree")
PROVIDER = "cashfree"
MAX_ADVANCE_DAYS = 13  # Cashfree: "the first charge date must be within a 14-day window"; one day of margin
NO_FREE_PERIOD_FIRST_CHARGE_DAYS = 2  # same-day and next-evening scheduling are cut off for UPI AutoPay and cards, so a purchase with no free period is first charged 2 days out
AUTH_OF = {
    "INITIALIZED": "initialized", "BANK_APPROVAL_PENDING": "bank_pending", "ACTIVE": "authorized", "ON_HOLD": "authorized", "COMPLETED": "authorized",
    "PAUSED": "paused", "CUSTOMER_PAUSED": "paused", "CARD_EXPIRED": "card_expired",
    "LINK_EXPIRED": "expired", "EXPIRED": "expired", "CUSTOMER_CANCELLED": "cancelled", "CANCELLED": "cancelled",
}
LIVE_AUTH = ("initialized", "bank_pending", "authorized")
PAYMENT_STATUS = {"SUCCESS": "captured", "FAILED": "failed", "CANCELLED": "failed", "USER_DROPPED": "failed", "PENDING": "created", "INITIALIZED": "created"}
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


# ----------------------------------------------------------------------------------------------------------------------------------- plans and prices
def plan_max_amount_paise(db: Session) -> int:
    """The mandate's ceiling. The highest active plan price, so a plan change never needs a new authorisation. The customer is only ever charged their plan's price."""
    if settings.cashfree_plan_max_amount_paise:
        return settings.cashfree_plan_max_amount_paise
    return max((p.price_paise for p in db.scalars(select(BillingPlan).where(BillingPlan.is_active.is_(True)))), default=0)


def cf_plan_id(plan: BillingPlan) -> str:
    return f"flowqr-{plan.code}-{plan.price_paise}"[:40]  # tied to the amount: a plan's amount cannot be edited at Cashfree, so a new price is a new plan


def ensure_plan(db: Session, client: cf.CashfreeClient, plan: BillingPlan) -> str:
    res = client.ensure_plan(plan_id=cf_plan_id(plan), name=f"FlowQR {plan.name}", amount_paise=plan.price_paise, max_amount_paise=plan_max_amount_paise(db))
    plan.cashfree_plan_id = res.plan_id
    db.flush()
    return res.plan_id


# ----------------------------------------------------------------------------------------------------------------------------------- what the customer is told first
def first_charge_at_for(db: Session, sub: Subscription, now: datetime | None = None) -> tuple[datetime, bool]:
    """(when the first monthly charge happens, whether a free period is being honoured). Raises 409 if the free period is too far away for Cashfree to schedule."""
    now = now or utcnow()
    free_until = None
    if sub.status == "incomplete":
        # No trial exists yet. The first payment is scheduled for day 8 from now (the trial is 7 days, then the first monthly payment). The trial itself starts only once Cashfree confirms the authorisation.
        first = (now.astimezone(timezone(timedelta(hours=5, minutes=30))) + timedelta(days=settings.trial_days + 1)).replace(hour=10, minute=0, second=0, microsecond=0)
        return first.astimezone(timezone.utc), True
    if sub.status == "trialing" and sub.trial_ends_at:
        free_until = _aware(sub.trial_ends_at)
    elif sub.status == "canceled" and sub.current_period_end and _aware(sub.current_period_end) > now:
        free_until = _aware(sub.current_period_end)  # re-subscribing during a paid period that is already ending
    if free_until and free_until > now + timedelta(minutes=30):
        if free_until > now + timedelta(days=MAX_ADVANCE_DAYS):
            earliest = free_until - timedelta(days=MAX_ADVANCE_DAYS)
            raise HTTPException(status_code=409, detail={"code": "too_early", "message": f"You can choose a plan from {earliest:%d %b %Y}: Cashfree can schedule a first payment up to {MAX_ADVANCE_DAYS} days ahead.",
                                                         "earliest": earliest.isoformat()})
        return free_until, True
    ist = timezone(timedelta(hours=5, minutes=30))
    day = (now.astimezone(ist) + timedelta(days=NO_FREE_PERIOD_FIRST_CHARGE_DAYS)).replace(hour=10, minute=0, second=0, microsecond=0)
    return day.astimezone(timezone.utc), False


def disclosure(db: Session, sub: Subscription, plan: BillingPlan, now: datetime | None = None) -> dict:
    """Everything the checkout screen must say BEFORE the customer reaches Cashfree. The wording is built on the frontend from these numbers, never from the browser's own."""
    first, free = first_charge_at_for(db, sub, now)
    return {"plan": plan.code, "plan_name": plan.name, "amount_paise": plan.price_paise, "currency": plan.currency, "first_charge_at": first, "free_period_honoured": free,
            "authorization_paise": settings.cashfree_authorization_paise, "authorization_refunded": True, "mandate_ceiling_paise": plan_max_amount_paise(db),
            "methods": settings.cashfree_method_list}


# ----------------------------------------------------------------------------------------------------------------------------------- checkout
def _owner_customer(user: User, tenant: Tenant, phone: str | None) -> cf.Customer:
    number = "".join(ch for ch in (phone or user.phone or tenant.phone or "") if ch.isdigit())[-10:]
    if len(number) != 10:
        raise HTTPException(status_code=422, detail={"code": "phone_required", "message": "Enter the mobile number linked to your bank or UPI app (10 digits) so Cashfree can set up the payment."})
    return cf.Customer(name=(user.full_name or tenant.name or "FlowQR customer")[:100], email=user.email, phone=number)


def new_subscription_id() -> str:
    return "fqs_" + secrets.token_hex(10)  # our merchant id: random, so it can never be guessed or derived from a tenant


TERMINAL = {"CANCELLED", "CUSTOMER_CANCELLED", "EXPIRED", "LINK_EXPIRED", "COMPLETED"}


def _retire_old_mandate(db: Session, client: cf.CashfreeClient, sub: Subscription) -> None:
    """A new authorisation replaces an old one that is NOT live from our side (paused, expired card...). The old one is cancelled at Cashfree first unless it is already finished there, so a
    mandate the customer resumes later can never be charged alongside the new one. If it cannot be checked or cancelled, nothing is created."""
    if not sub.cashfree_subscription_id or sub.authorization_status in ("initialized",):
        return
    try:
        old = client.fetch_subscription(sub.cashfree_subscription_id)
        if old.status not in TERMINAL:
            client.cancel_subscription(sub.cashfree_subscription_id)
    except cf.CashfreeError:
        raise HTTPException(status_code=409, detail={"code": "mandate_change_failed", "message": "We couldn't close your earlier payment authorisation yet, so nothing new was set up. Please try again in a moment."})
    svc.log_event(db, sub.tenant_id, "mandate_replaced", source="user", ref=sub.cashfree_subscription_id, meta={"was": sub.authorization_status})


def start_checkout(db: Session, client: cf.CashfreeClient, *, sub: Subscription, plan: BillingPlan, user: User, tenant: Tenant, phone: str | None, now: datetime | None = None) -> dict:
    now = now or utcnow()
    if not settings.cashfree_configured:
        raise HTTPException(status_code=503, detail={"code": "billing_config_pending", "message": "Online payments aren't configured on this server yet."})
    live = sub.cashfree_subscription_id and sub.authorization_status in LIVE_AUTH
    if live and sub.status in ("active", "past_due") or (live and sub.authorization_status in ("bank_pending", "authorized")):
        raise HTTPException(status_code=409, detail={"code": "already_subscribed", "message": "You already have a payment set up. Use change plan instead."})
    if live and sub.authorization_status == "initialized":
        try:
            remote = client.fetch_subscription(sub.cashfree_subscription_id)
        except cf.CashfreeError:
            raise HTTPException(status_code=502, detail="Payment provider error. Please try again.")
        if remote.status == "INITIALIZED" and sub.pending_plan == plan.code and remote.session_id:
            return {**disclosure(db, sub, plan, now), "subscription_session_id": remote.session_id, "environment": settings.cashfree_env, "reused": True}
        if remote.status == "INITIALIZED":  # a different plan was started and not finished: close it first so two mandates can never both be authorised
            try:
                client.cancel_subscription(sub.cashfree_subscription_id)
            except cf.CashfreeError:
                raise HTTPException(status_code=409, detail={"code": "checkout_in_progress", "message": "Finish or cancel the payment setup you already started, then try again."})
            svc.log_event(db, sub.tenant_id, "checkout_replaced", source="user", ref=sub.cashfree_subscription_id, meta={"from_plan": sub.pending_plan, "to_plan": plan.code})
    _retire_old_mandate(db, client, sub)
    info = disclosure(db, sub, plan, now)
    customer = _owner_customer(user, tenant, phone)
    plan_id = ensure_plan(db, client, plan)
    sid = new_subscription_id()
    # While the business is still being set up the customer returns INTO onboarding (the app shell would send them there anyway); afterwards to the billing return page
    return_url = (f"{settings.frontend_url.rstrip('/')}/onboarding?checkout=return" if not tenant.onboarding_completed else f"{settings.frontend_url.rstrip('/')}/settings/billing/return?s={sid}")
    try:
        created = client.create_subscription(subscription_id=sid, plan_id=plan_id, customer=customer, first_charge_at=info["first_charge_at"], authorization_paise=settings.cashfree_authorization_paise,
                                             refund_authorization=True, methods=settings.cashfree_method_list, return_url=return_url, idempotency_key=str(uuid.uuid5(uuid.NAMESPACE_URL, f"flowqr-sub:{sid}")))
    except cf.CashfreeError as exc:
        log.warning("create_subscription failed: %s %s", exc.status, exc.code)
        raise HTTPException(status_code=502, detail="Payment provider error. Please try again.")
    if not created.session_id:
        raise HTTPException(status_code=502, detail="Payment provider error. Please try again.")
    sub.provider, sub.cashfree_subscription_id, sub.cashfree_cf_subscription_id = PROVIDER, sid, created.cf_id
    sub.authorization_status, sub.pending_plan = "initialized", plan.code
    sub.first_charge_at = sub.next_charge_at = info["first_charge_at"]
    if sub.status in ("expired", "halted"):
        sub.status = "pending"
    svc.log_event(db, sub.tenant_id, "checkout_created", source="user", ref=sid, meta={"plan": plan.code, "first_charge_at": info["first_charge_at"].isoformat(), "free_period": info["free_period_honoured"]})
    return {**info, "subscription_session_id": created.session_id, "environment": settings.cashfree_env, "reused": False}


# ----------------------------------------------------------------------------------------------------------------------------------- applying what Cashfree says
def _upsert_payment(db: Session, sub: Subscription, p: cf.PaymentResult, now: datetime) -> tuple[Payment | None, bool, bool]:
    """-> (row, newly_captured, newly_failed). Monotonic: a captured payment never goes back. A payment id already stored for ANOTHER business is ignored."""
    if not p.payment_id:
        return None, False, False
    status = PAYMENT_STATUS.get(p.status, "created")
    row = db.scalar(select(Payment).where(Payment.cashfree_payment_id == p.payment_id))
    if row is not None and row.tenant_id != sub.tenant_id:
        log.error("cashfree payment id already belongs to another business: ignored")
        return None, False, False
    kind = "sub_auth" if p.payment_type == "AUTH" else "subscription"
    created_at = p.initiated_at or now
    if row is None:
        row = Payment(tenant_id=sub.tenant_id, kind=kind, status=status, amount_paise=p.amount_paise, currency="INR", provider=PROVIDER, cashfree_payment_id=p.payment_id, cashfree_cf_payment_id=p.cf_payment_id,
                      payment_type=p.payment_type, method=(p.method or None) and p.method[:24], failure_reason=p.failure_reason if status == "failed" else None, created_at=created_at,
                      paid_at=(p.initiated_at or now) if status == "captured" else None, meta={})
        try:
            with db.begin_nested():  # a payment id that exists for ANOTHER business may be invisible here (row-level security): the database's unique constraint then refuses it, and it is ignored
                db.add(row)
                db.flush()
        except IntegrityError:
            log.error("cashfree payment id already exists for another business: ignored")
            return None, False, False
        return row, status == "captured", status == "failed"
    newly_captured = status == "captured" and row.status != "captured"
    newly_failed = status == "failed" and row.status not in ("failed", "captured")
    if row.status != "captured":
        row.status = status
    if status == "captured" and row.paid_at is None:
        row.paid_at = p.initiated_at or now
    if status == "failed":
        row.failure_reason = p.failure_reason or row.failure_reason
    row.method = (p.method or row.method or None) and (p.method or row.method)[:24]
    row.cashfree_cf_payment_id = p.cf_payment_id or row.cashfree_cf_payment_id
    return row, newly_captured, newly_failed


def _plus_month(d: datetime) -> datetime:
    y, m = (d.year + (d.month // 12), d.month % 12 + 1)
    for day in (d.day, 30, 29, 28):
        try:
            return d.replace(year=y, month=m, day=day)
        except ValueError:
            continue
    return d + timedelta(days=30)


def _on_charge_success(db: Session, sub: Subscription, row: Payment, remote: cf.SubscriptionResult, now: datetime, *, source: str, ref: str | None) -> None:
    if sub.status == "canceled":
        # money arrived after the customer cancelled: never silently re-activate. Recorded for finance; an administrator decides on a refund.
        svc.log_event(db, sub.tenant_id, "charge_after_cancel", source=source, ref=row.cashfree_payment_id, meta={"amount_paise": row.amount_paise})
        return
    prices = {p.code: p.price_paise for p in db.scalars(select(BillingPlan))}
    pend = sub.pending_plan
    if pend and prices.get(pend) == row.amount_paise:
        target = pend  # the plan chosen at checkout, or a scheduled change that has now reached its billing boundary
    elif sub.plan in prices and prices[sub.plan] == row.amount_paise:
        target = sub.plan
    else:
        target = None
    if target is None:
        svc.log_event(db, sub.tenant_id, "amount_mismatch", source=source, ref=row.cashfree_payment_id, meta={"amount_paise": row.amount_paise, "plan": sub.plan, "pending": pend})
        audit(db, action="billing.cashfree.amount_mismatch", tenant_id=sub.tenant_id, entity_type="subscription", entity_id=sub.id, meta={"amount_paise": row.amount_paise})
        return  # entitlements are not changed on an amount nobody can explain
    before = svc.snapshot(sub)
    was_active = sub.status == "active"
    svc.apply_plan(sub, db.get(BillingPlan, target))
    sub.plan = target
    if pend == target:
        sub.pending_plan = None  # a scheduled change is consumed only by a charge of the NEW amount: a charge of the old amount leaves it waiting
    sub.status, sub.source, sub.provider = "active", PROVIDER, PROVIDER
    sub.past_due_since, sub.trial_ends_at, sub.cancel_at_period_end = None, None, False
    start = _aware(row.paid_at) or now
    sub.current_period_start = start
    sub.current_period_end = _aware(remote.next_charge_at) or _plus_month(start)
    sub.next_charge_at = remote.next_charge_at
    row.period_start, row.period_end = sub.current_period_start, sub.current_period_end
    svc.record_change(db, sub, before, source=source, ref=ref or row.cashfree_payment_id, kind="renewed" if was_active else "activated", meta={"amount_paise": row.amount_paise, "plan": target})


def _mark_past_due(sub: Subscription, now: datetime) -> None:
    if sub.status in ("active", "trialing", "pending"):
        sub.status = "past_due"
        sub.past_due_since = sub.past_due_since or now


def _owners(db: Session, tenant_id: uuid.UUID) -> list[User]:
    return list(db.scalars(select(User).join(Membership, Membership.user_id == User.id).where(Membership.tenant_id == tenant_id, Membership.role == Role.owner, User.is_active.is_(True))))


def notify_payment_failed(db: Session, sub: Subscription, reason: str | None) -> None:
    grace = (_aware(sub.past_due_since) or utcnow()) + timedelta(days=settings.past_due_grace_days)
    body = ("Your FlowQR payment didn't go through.\n\n"
            f"Your access continues until {grace:%d %b %Y}. {('Reason given by your bank: ' + reason[:120] + '.') if reason else ''}\n\n"
            "What to do: make sure your bank account or UPI app has enough balance and the payment is allowed. We will ask your bank to try again. "
            f"If it keeps failing, open {settings.frontend_url.rstrip('/')}/settings/billing to set up the payment again.\n\n"
            f"Need help? Write to {settings.support_email or 'FlowQR support'}.")
    for u in _owners(db, sub.tenant_id):
        send_email(u.email, "Your FlowQR payment didn't go through", body)


def _apply_status(sub: Subscription, remote: cf.SubscriptionResult, now: datetime) -> None:
    s = remote.status
    auth = AUTH_OF.get(s)
    if auth is None:
        log.warning("unknown Cashfree subscription status %r: state left unchanged", s[:30])
        return
    sub.authorization_status = auth
    if sub.status == "incomplete":  # abandoned or failed authorisation: still incomplete, retry is allowed; nothing is unlocked and nothing was ever cancelled for the customer
        if s in ("LINK_EXPIRED", "EXPIRED", "CANCELLED", "CUSTOMER_CANCELLED", "COMPLETED"):
            sub.pending_plan = None
        return
    if s == "ON_HOLD":
        _mark_past_due(sub, now)
    elif s in ("PAUSED", "CUSTOMER_PAUSED", "CARD_EXPIRED"):
        if sub.status == "active":
            _mark_past_due(sub, now)  # the next charge cannot happen
    elif s in ("CUSTOMER_CANCELLED", "CANCELLED"):
        if sub.status != "canceled":
            sub.status, sub.canceled_at, sub.cancel_at_period_end = "canceled", now, True  # access continues to current_period_end, exactly as entitlements already rules
    elif s in ("COMPLETED", "EXPIRED"):
        if sub.status in ("active", "past_due", "trialing", "pending"):
            sub.status = "expired"
    elif s == "LINK_EXPIRED":
        sub.pending_plan = None  # checkout abandoned; the free period is untouched
        if sub.status == "pending":
            sub.status = "trialing" if (sub.trial_ends_at and _aware(sub.trial_ends_at) > now) else "expired"


def _start_trial_if_authorized(db: Session, sub: Subscription, remote: cf.SubscriptionResult, now: datetime, *, source: str, ref: str | None) -> str | None:
    """The ONLY place a mandate-gated trial begins, and only from the provider's own answer (never from a redirect or a query parameter). Cashfree's ACTIVE means the mandate is registered; that is
    the authorisation. Returns 'started', 'stale' (authorised too late for the trial to be honoured: cancel it) or None."""
    if sub.status != "incomplete" or remote.status != "ACTIVE" or sub.provider != PROVIDER:
        return None
    first = _aware(sub.first_charge_at)
    if first is None or first <= now + timedelta(days=1):
        return "stale"
    before = svc.snapshot(sub)
    chosen = db.get(BillingPlan, sub.pending_plan) if sub.pending_plan else None
    if chosen is not None and chosen.is_active:
        # The trial grants the features and limits of the plan the customer SELECTED (owner decision), copied onto the subscription row that every route and worker reads: so it is
        # enforced server-side everywhere, and persisted (`trial_plan`). `sub.plan` stays 'trial' until the first successful charge makes it the paid plan.
        svc.apply_plan(sub, chosen)
        sub.plan, sub.trial_plan = "trial", chosen.code
    sub.status, sub.source = "trialing", "trial"
    sub.trial_started_at = now
    sub.trial_ends_at = min(now + timedelta(days=settings.trial_days), first)
    sub.current_period_start, sub.current_period_end = now, sub.trial_ends_at
    svc.record_change(db, sub, before, source=source, ref=ref, kind="trial_started", meta={"days": settings.trial_days, "via": "cashfree_authorization", "first_charge_at": first.isoformat(), "entitlements_of": sub.trial_plan})
    return "started"


def apply_remote(db: Session, sub: Subscription, remote: cf.SubscriptionResult, payments: list[cf.PaymentResult], *, source: str, ref: str | None = None, now: datetime | None = None,
                 client: cf.CashfreeClient | None = None) -> dict:
    """Idempotent. Applying the same answer twice changes nothing the second time."""
    now = now or utcnow()
    before = svc.snapshot(sub)
    sub.last_provider_sync_at = now
    sub.cashfree_cf_subscription_id = remote.cf_id or sub.cashfree_cf_subscription_id
    if remote.first_charge_at:
        sub.first_charge_at = remote.first_charge_at
    if remote.next_charge_at:
        sub.next_charge_at = remote.next_charge_at
    captured = failed = 0
    for p in sorted(payments, key=lambda x: _aware(x.scheduled_for or x.initiated_at) or _EPOCH):
        row, newly_ok, newly_bad = _upsert_payment(db, sub, p, now)
        if row is None or row.kind == "sub_auth":
            continue
        if newly_ok:
            captured += 1
            _on_charge_success(db, sub, row, remote, now, source=source, ref=ref)
        elif newly_bad:
            failed += 1
            if sub.status in ("active", "trialing", "pending"):
                _mark_past_due(sub, now)
                svc.log_event(db, sub.tenant_id, "payment_failed", source=source, ref=row.cashfree_payment_id, from_status=before[0], to_status=sub.status, meta={"payment": row.cashfree_payment_id})
                notify_payment_failed(db, sub, row.failure_reason)
    _apply_status(sub, remote, now)  # always: a cancellation that arrives with a successful charge must still be applied (after the activation, so access runs to the period end)
    started = _start_trial_if_authorized(db, sub, remote, now, source=source, ref=ref)
    if started == "stale":
        # authorised so long after the checkout began that the day-8 charge is imminent: honouring a 7-day trial is impossible, and leaving the mandate live would charge without the trial the
        # customer was promised. Close it at Cashfree and let them start again.
        if client is not None:
            try:
                client.cancel_subscription(sub.cashfree_subscription_id)
                sub.authorization_status, sub.pending_plan = "cancelled", None
                svc.log_event(db, sub.tenant_id, "authorization_stale", source=source, ref=sub.cashfree_subscription_id)
            except cf.CashfreeError:
                log.warning("could not cancel a stale authorisation: it will be retried by the next sync")
    if sub.status != before[0] and not (captured or failed) and started is None:
        svc.record_change(db, sub, before, source=source, ref=ref, meta={"cashfree_status": remote.status})
    return {"captured": captured, "failed": failed, "status": sub.status}


def sync(db: Session, client: cf.CashfreeClient, sub: Subscription, *, source: str, ref: str | None = None) -> dict:
    """Read the truth from Cashfree and apply it. The only way state changes from the provider's side."""
    remote = client.fetch_subscription(sub.cashfree_subscription_id)
    payments = client.list_payments(sub.cashfree_subscription_id)
    return apply_remote(db, sub, remote, payments, source=source, ref=ref, client=client)


# ----------------------------------------------------------------------------------------------------------------------------------- webhooks
def record_event(db: Session, env: cf.WebhookEnvelope) -> tuple[WebhookEvent, bool]:
    """-> (row, is_new). A repeated delivery returns the stored row; `failed` and `retrying` rows are processed again, `processed` and `ignored` are not."""
    row = WebhookEvent(provider=PROVIDER, event_id=env.dedupe_key, event_type=env.type[:64], received_at=utcnow(), status="received", subscription_ref=env.subscription_id,
                       payment_ref=env.payment_id, payload_hash=env.payload_hash, attempts=0, provider_event_time=env.event_time)
    try:
        with db.begin_nested():
            db.add(row)
            db.flush()
        return row, True
    except IntegrityError:
        existing = db.scalar(select(WebhookEvent).where(WebhookEvent.event_id == env.dedupe_key))
        return existing, False


def handle_event(db: Session, client: cf.CashfreeClient, env: cf.WebhookEnvelope) -> str:
    sid = env.subscription_id
    if not sid:
        return "ignored"
    sub = db.scalar(select(Subscription).where(Subscription.cashfree_subscription_id == sid).with_for_update())  # OUR id only: nothing else in the payload picks a tenant
    if sub is None:
        return "ignored"
    out = sync(db, client, sub, source="webhook", ref=env.dedupe_key[:16])
    audit(db, action=f"billing.cashfree.{env.type.lower()}", tenant_id=sub.tenant_id, entity_type="subscription", entity_id=sub.id, meta={"status": sub.status, "plan": sub.plan, **out})
    return "processed"


def process_event(db: Session, client: cf.CashfreeClient, row: WebhookEvent, env: cf.WebhookEnvelope) -> str:
    row.attempts = (row.attempts or 0) + 1
    try:
        result = handle_event(db, client, env)
        row.status, row.processed_at, row.last_error = result, utcnow(), None
        return result
    except cf.CashfreeError as exc:
        row.status, row.last_error = "failed", f"provider {exc.status} {exc.code}"[:300]
        raise


# ----------------------------------------------------------------------------------------------------------------------------------- cancel, change plan
def cancel(db: Session, client: cf.CashfreeClient, sub: Subscription, *, user_id: uuid.UUID | None) -> None:
    if not sub.cashfree_subscription_id or sub.authorization_status not in ("initialized", "bank_pending", "authorized", "paused"):
        raise HTTPException(status_code=409, detail="There is no payment set up to cancel")
    try:
        client.cancel_subscription(sub.cashfree_subscription_id)  # Cashfree cancels at once; no further charge will ever be taken
    except cf.CashfreeError:
        raise HTTPException(status_code=502, detail="Cashfree couldn't cancel the payment. Please try again.")
    before, now = svc.snapshot(sub), utcnow()
    if sub.status == "incomplete":  # no trial was ever started: closing the authorisation just returns them to plan selection
        sub.authorization_status, sub.pending_plan = "cancelled", None
        svc.log_event(db, sub.tenant_id, "authorization_cancelled", source="user", ref=sub.cashfree_subscription_id)
        return
    sub.status, sub.canceled_at, sub.cancel_at_period_end, sub.authorization_status, sub.pending_plan = "canceled", now, True, "cancelled", None
    if sub.current_period_end is None or _aware(sub.current_period_end) < now:
        sub.current_period_end = _aware(sub.trial_ends_at) if sub.trial_ends_at and _aware(sub.trial_ends_at) > now else now
    svc.record_change(db, sub, before, source="user", kind="cancel_requested", meta={"access_until": sub.current_period_end.isoformat(), "by": str(user_id) if user_id else None})


def change_plan(db: Session, client: cf.CashfreeClient, sub: Subscription, target: BillingPlan, current: BillingPlan | None) -> dict:
    """Both directions take effect at the NEXT successful monthly charge (no proration, no extra charge). Cashfree is told the new plan now, so the next charge is the new amount."""
    if not sub.cashfree_subscription_id or sub.authorization_status != "authorized" or sub.status not in ("active", "trialing"):
        raise HTTPException(status_code=409, detail="Set up the payment first, then you can change plans.")
    if current and current.code == target.code and not sub.pending_plan:
        raise HTTPException(status_code=409, detail="You're already on this plan")
    if target.price_paise > plan_max_amount_paise(db):
        raise HTTPException(status_code=409, detail="That plan needs a new payment authorisation. Start a new checkout for it.")
    try:
        client.change_plan(sub.cashfree_subscription_id, ensure_plan(db, client, target))
    except cf.CashfreeError:
        raise HTTPException(status_code=502, detail="Cashfree couldn't change the plan. Please try again.")
    effective = sub.next_charge_at or sub.first_charge_at
    back_to_current = bool(current and current.code == target.code)
    sub.pending_plan = None if back_to_current else target.code
    svc.log_event(db, sub.tenant_id, "plan_change_scheduled", source="user", from_plan=sub.plan, to_plan=target.code, meta={"effective": effective.isoformat() if effective else None, "data_kept": True})
    return {"plan": sub.plan, "pending_plan": sub.pending_plan, "effective_at": effective}


# ----------------------------------------------------------------------------------------------------------------------------------- reconciliation (scheduled)
def _candidates(db: Session, now: datetime, limit: int) -> list[Subscription]:
    cutoff = now - timedelta(minutes=15)
    soon = now + timedelta(days=1)
    q = select(Subscription).where(
        Subscription.cashfree_subscription_id.is_not(None),
        or_(Subscription.status.in_(("pending", "past_due")), Subscription.authorization_status.in_(("initialized", "bank_pending")),
            and_(Subscription.status == "trialing", Subscription.authorization_status == "authorized", Subscription.first_charge_at <= soon),
            and_(Subscription.status == "active", Subscription.next_charge_at <= soon)),
        or_(Subscription.last_provider_sync_at.is_(None), Subscription.last_provider_sync_at < cutoff)).limit(limit)
    return list(db.scalars(q))


def maybe_retry(db: Session, client: cf.CashfreeClient, sub: Subscription, payments: list[cf.PaymentResult], now: datetime) -> bool:
    """A failed CARD charge is not retried by Cashfree itself (UPI AutoPay is), so ask Cashfree to retry it: its own documented call, at most 3 per cycle, once a day, inside the grace period."""
    if sub.status != "past_due" or not sub.past_due_since or now >= _aware(sub.past_due_since) + timedelta(days=settings.past_due_grace_days):
        return False
    charges = [p for p in payments if p.payment_type == "CHARGE"]
    last = max(charges, key=lambda p: _aware(p.scheduled_for or p.initiated_at) or _EPOCH, default=None)
    if last is None or last.status != "FAILED" or last.method != "card" or last.retry_attempts >= settings.cashfree_retry_max:
        return False
    row = db.scalar(select(Payment).where(Payment.cashfree_payment_id == last.payment_id, Payment.tenant_id == sub.tenant_id))
    if row is None:
        return False
    stamp = (row.meta or {}).get("last_retry_at")
    if stamp and datetime.fromisoformat(stamp) > now - timedelta(hours=20):
        return False
    ist = timezone(timedelta(hours=5, minutes=30))
    try:
        client.retry_payment(sub.cashfree_subscription_id, last.payment_id, (now.astimezone(ist) + timedelta(days=1)).date())
    except cf.CashfreeError as exc:
        log.warning("retry failed: %s %s", exc.status, exc.code)
        return False
    row.meta = {**(row.meta or {}), "last_retry_at": now.isoformat()}
    svc.log_event(db, sub.tenant_id, "retry_requested", source="system", ref=last.payment_id, meta={"attempt": last.retry_attempts + 1})
    return True


def retry_now(db: Session, client: cf.CashfreeClient, sub: Subscription) -> bool:
    """Owner pressed 'retry': ask Cashfree to retry the failed card charge. Same limits as the hourly job (card only, once a day, at most 3 a cycle, inside the grace period)."""
    if not sub.cashfree_subscription_id:
        return False
    return maybe_retry(db, client, sub, client.list_payments(sub.cashfree_subscription_id), utcnow())


def reconcile(db: Session, client: cf.CashfreeClient, *, now: datetime | None = None, limit: int = 200) -> dict:
    """Hourly safety net, because Cashfree does not replay missed webhooks. Reads and applies; the only write to Cashfree is `maybe_retry`."""
    now = now or utcnow()
    done = errors = retries = 0
    for sub in _candidates(db, now, limit):
        try:
            remote = client.fetch_subscription(sub.cashfree_subscription_id)
            payments = client.list_payments(sub.cashfree_subscription_id)
            apply_remote(db, sub, remote, payments, source="system", ref="reconcile", now=now, client=client)
            retries += 1 if maybe_retry(db, client, sub, payments, now) else 0
            db.commit()
            done += 1
        except cf.CashfreeError:
            db.rollback()
            errors += 1
        except Exception:  # one business must never stop the others
            db.rollback()
            errors += 1
            log.exception("reconcile failed for one subscription")
    return {"synced": done, "errors": errors, "retries_requested": retries}


# ----------------------------------------------------------------------------------------------------------------------------------- what the screens show
def billing_state(sub: Subscription | None, now: datetime | None = None) -> str:
    """The brief's state names, derived (never stored): pending, authorization_pending, trialing, active, past_due, cancellation_pending, cancelled, expired."""
    if sub is None:
        return "none"
    now = now or utcnow()
    if sub.status == "canceled":
        return "cancellation_pending" if sub.current_period_end and _aware(sub.current_period_end) > now else "cancelled"
    if sub.status == "past_due":
        return "past_due"
    if sub.status == "incomplete":
        return "authorization_pending" if sub.authorization_status in ("initialized", "bank_pending") else "authorization_required"
    if sub.provider == PROVIDER and sub.authorization_status in ("initialized", "bank_pending"):
        return "authorization_pending"
    return {"pending": "pending", "trialing": "trialing", "active": "active", "expired": "expired", "halted": "expired", "manual": "active"}.get(sub.status, sub.status)
