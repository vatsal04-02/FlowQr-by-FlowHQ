"""Razorpay subscriptions + physical-card orders. Owner-only for money actions."""
import json
import logging
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import get_db, set_rls_context
from app.core.deps import TenantContext, ensure_verified, get_tenant_context, require_role
from app.core.rate_limit import client_ip, limit_by_ip
from app.models import BillingPlan, CardOrder, Payment, PromotionalGrant, Role, Subscription, SubscriptionEvent, Tenant
from app.models.base import utcnow
from app.schemas.billing import (
    CancelIn, CardOrderIn, CardOrderOut, ChangePlanIn, CheckoutIn, PaymentOut, PlanOut, PrepaidCheckoutIn, PrepaidVerifyIn, VerifyOrderIn, VerifySubscriptionIn,
)
from app.services import billing as svc
from app.services import billing_cashfree as cfb
from app.services import cashfree as cashfree_svc
from app.services import entitlements as ent
from app.services import plans as plans_svc
from app.services import prepaid
from app.services import razorpay as rz
from app.services.ai_usage import usage_this_month
from app.services.audit import audit
from sqlalchemy.orm import Session

log = logging.getLogger("flowqr.billing")
router = APIRouter(prefix="/billing", tags=["billing"])


def _client():
    try:
        return rz.get_razorpay()
    except rz.RazorpayNotConfigured:
        raise HTTPException(status_code=503, detail={"code": "billing_config_pending",
                            "message": "Online payments aren't configured on this server yet (Razorpay keys missing)."})


def _cf_client():
    try:
        return cashfree_svc.get_cashfree()
    except cashfree_svc.CashfreeNotConfigured:
        raise HTTPException(status_code=503, detail={"code": "billing_config_pending", "message": "Online payments aren't configured on this server yet."})


def _config() -> dict:
    if settings.cashfree_enabled:
        return {"configured": settings.cashfree_configured, "provider": "cashfree", "mode": "test" if (settings.cashfree_env or "").lower() == "sandbox" else "live", "key_id": None,
                "authorization_paise": settings.cashfree_authorization_paise, "methods": settings.cashfree_method_list, "mandate_required": settings.mandate_required}
    return {"configured": settings.razorpay_configured, "mode": settings.razorpay_mode, "provider": "razorpay" if settings.razorpay_configured else None,
            "key_id": settings.razorpay_key_id if settings.razorpay_configured else None}


@router.get("/plans")
def plans(db: Session = Depends(get_db)):
    """Public: used by the pricing page."""
    set_rls_context(db, bypass=True)
    rows = db.scalars(select(BillingPlan).where(BillingPlan.is_active.is_(True)).order_by(BillingPlan.sort_order)).all()
    offers = [{"code": o["code"], "quantity": o["quantity"], "price_paise": o["price_paise"], "includes": f"{settings.promo_card_days} days of {settings.promo_card_plan.title()}"} for o in (settings.card_offers or [])]
    return {"plans": [PlanOut.model_validate(p) for p in rows], "terms": plans_svc.public_terms(), "trial_days": settings.trial_days,
            "billing": _config(), "card_price_paise": settings.card_price_paise,
            "card_ordering_enabled": (bool(settings.card_price_paise) or bool(offers)) and settings.razorpay_configured, "card_offers": offers,
            "card_offer_note": "Card prices are one-time purchases, separate from any subscription. The included month is free access, not a subscription: nothing is charged when it ends."}


@router.get("/subscription")
def subscription(ctx: TenantContext = Depends(get_tenant_context)):
    sub = ctx.db.scalar(select(Subscription).where(Subscription.tenant_id == ctx.tenant_id))
    e = ent.for_tenant(ctx.db, ctx.tenant_id)
    plan = ctx.db.get(BillingPlan, sub.plan) if sub else None
    return {
        "billing": _config(),
        "status": e.status, "active": e.active, "inactive_reason": e.reason, "plan": sub.plan if sub else None,
        "plan_name": plan.name if plan else ("Free trial" if sub and sub.plan == "trial" else None),
        "price_paise": plan.price_paise if plan else None,
        "trial_ends_at": sub.trial_ends_at if sub else None, "trial_days_left": e.trial_days_left,
        "current_period_end": sub.current_period_end if sub else None, "cancel_at_period_end": bool(sub and sub.cancel_at_period_end),
        "pending_plan": sub.pending_plan if sub else None, "grace_until": e.grace_until, "source": sub.source if sub else None,
        "has_razorpay_subscription": bool(sub and sub.razorpay_subscription_id),
        "provider": sub.provider if sub else None, "has_cashfree_subscription": bool(sub and sub.cashfree_subscription_id), "mandate_required": settings.mandate_required,
        "trial_started_at": sub.trial_started_at if sub else None, "payment_method": _payment_method(ctx.db, ctx.tenant_id),
        "trial_entitlement": sub.trial_entitlement if sub else None, "trial_entitlement_name": (ctx.db.get(BillingPlan, sub.trial_entitlement).name if sub and sub.trial_entitlement and ctx.db.get(BillingPlan, sub.trial_entitlement) else None),
        "selected_plan": _selected_plan(sub), "selected_plan_name": (ctx.db.get(BillingPlan, _selected_plan(sub)).name if _selected_plan(sub) and ctx.db.get(BillingPlan, _selected_plan(sub)) else None),
        "next_charge_amount_paise": _next_amount(ctx.db, sub),
        "authorization_status": sub.authorization_status if sub else None, "billing_state": cfb.billing_state(sub),
        "first_charge_at": sub.first_charge_at if sub else None, "next_charge_at": sub.next_charge_at if sub else None,
        "pending_plan_name": (ctx.db.get(BillingPlan, sub.pending_plan).name if sub and sub.pending_plan and ctx.db.get(BillingPlan, sub.pending_plan) else None),
        "pending_plan_effective_at": (sub.next_charge_at or sub.first_charge_at) if sub and sub.pending_plan else None,
        "promo": None if not e.promo else {**e.promo, "note": "Included free with your card purchase. It ends on its own and nothing is charged."},
        "limits": {"locations": e.max_locations, "ai_generations": e.monthly_ai_generations, "review_generations": e.review_generations, "review_replies": e.review_replies,
                   "staff": e.max_staff, "features": sorted(e.features)},
        "usage": {"locations": ent.locations_used(ctx.db, ctx.tenant_id), "ai_generations": usage_this_month(ctx.db, ctx.tenant_id),
                  "review_generations": usage_this_month(ctx.db, ctx.tenant_id, field="review_generations"), "review_replies": usage_this_month(ctx.db, ctx.tenant_id, field="review_replies"),
                  "staff": ent.seats_used(ctx.db, ctx.tenant_id)},
    }


def _payment_method(db: Session, tenant_id) -> str | None:
    """The kind of method Cashfree reported for the authorisation or the latest payment ("upi", "card"). Only the kind: no card number, no UPI id is stored or shown."""
    row = db.scalar(select(Payment).where(Payment.tenant_id == tenant_id, Payment.provider == "cashfree", Payment.method.is_not(None)).order_by(Payment.created_at.desc()).limit(1))
    return row.method if row else None


def _selected_plan(sub) -> str | None:
    """The paid plan this customer chose and will be billed on after the trial. During checkout and the trial it is `pending_plan` (the trial itself carries Growth's entitlements whatever was chosen);
    once a payment has gone through it is the current plan, or the scheduled change."""
    if sub is None:
        return None
    if sub.status in ("incomplete", "trialing") or sub.plan == "trial":
        return sub.pending_plan
    return sub.pending_plan or sub.plan


def _next_amount(db: Session, sub) -> int | None:
    if sub is None or sub.provider != "cashfree" or sub.authorization_status not in ("authorized", "bank_pending"):
        return None
    plan = db.get(BillingPlan, sub.pending_plan or sub.plan)
    return plan.price_paise if plan else None


@router.get("/subscription/history")
def subscription_history(ctx: TenantContext = Depends(require_role(Role.admin)), limit: int = Query(100, ge=1, le=500)):
    """Everything that happened to this business's subscription, newest first (plan changes, payments failing, cancellations, refunds, promotional months)."""
    rows = ctx.db.scalars(select(SubscriptionEvent).where(SubscriptionEvent.tenant_id == ctx.tenant_id).order_by(SubscriptionEvent.created_at.desc()).limit(limit)).all()
    return {"events": [{"at": r.created_at, "kind": r.kind, "from_status": r.from_status, "to_status": r.to_status, "from_plan": r.from_plan, "to_plan": r.to_plan, "source": r.source, "meta": r.meta} for r in rows]}


def _locked_sub(ctx: TenantContext) -> Subscription:
    sub = ctx.db.scalar(select(Subscription).where(Subscription.tenant_id == ctx.tenant_id).with_for_update())
    if not sub:
        raise HTTPException(status_code=404, detail="No subscription found")
    return sub


def _cashfree_checkout(body: CheckoutIn, request: Request, ctx: TenantContext) -> dict:
    """Cashfree: the server prices the plan, shows what will happen (see `disclosure`), creates the mandate request and hands back a session for Cashfree's hosted checkout."""
    client = _cf_client()
    sub = _locked_sub(ctx)
    plan = ctx.db.get(BillingPlan, body.plan)
    if not plan or not plan.is_active:
        raise HTTPException(status_code=404, detail="Unknown plan")
    tenant = ctx.db.get(Tenant, ctx.tenant_id)
    out = cfb.start_checkout(ctx.db, client, sub=sub, plan=plan, user=ctx.user, tenant=tenant, phone=body.phone)
    audit(ctx.db, action="billing.checkout_created", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="subscription", entity_id=sub.id,
          meta={"plan": plan.code, "provider": "cashfree", "reused": out["reused"]}, ip=client_ip(request))
    ctx.db.commit()
    return out


@router.post("/subscription/checkout")
def checkout(body: CheckoutIn, request: Request, ctx: TenantContext = Depends(require_role(Role.owner))):
    """Creates (or re-uses) a Razorpay subscription for the chosen plan. Idempotent per tenant+plan."""
    ensure_verified(ctx.user)
    if settings.cashfree_enabled:
        return _cashfree_checkout(body, request, ctx)
    client = _client()
    sub = _locked_sub(ctx)
    plan = ctx.db.get(BillingPlan, body.plan)
    if not plan or not plan.is_active:
        raise HTTPException(status_code=404, detail="Unknown plan")
    if sub.razorpay_subscription_id and sub.status in ("active", "past_due"):
        raise HTTPException(status_code=409, detail="You already have a subscription. Use change plan instead.")
    try:
        if sub.razorpay_subscription_id and sub.pending_plan == plan.code and sub.status in ("pending", "trialing"):
            existing = client.fetch_subscription(sub.razorpay_subscription_id)
            if existing.get("status") in ("created", "authenticated"):  # reuse the open checkout: no duplicates
                return {"subscription_id": sub.razorpay_subscription_id, "key_id": settings.razorpay_key_id, "plan": plan.code, "reused": True}
        rzp_plan_id = svc.ensure_razorpay_plan(ctx.db, client, plan)
        start_at = None
        from datetime import timedelta
        free_until = sub.trial_ends_at if sub.status == "trialing" and sub.trial_ends_at else None  # the free trial is carried into whichever plan is chosen
        promo = ent.active_promo(ctx.db, ctx.tenant_id)
        if promo and (free_until is None or promo[0].ends_at > free_until):
            free_until = promo[0].ends_at
        if free_until and free_until > utcnow() + timedelta(minutes=10):
            start_at = int(free_until.timestamp())  # no charge until the free period (trial or card month) ends; choosing a plan here is the explicit consent
        created = client.create_subscription(plan_id=rzp_plan_id, total_count=120, start_at=start_at,
                                             notes={"tenant_id": str(ctx.tenant_id), "plan": plan.code})
    except rz.RazorpayError as exc:
        ctx.db.rollback()
        log.warning("Razorpay checkout failed: %s", exc)
        raise HTTPException(status_code=502, detail="Payment provider error. Please try again.")
    sub.razorpay_subscription_id = created["id"]
    sub.pending_plan = plan.code
    if sub.status != "trialing":
        sub.status = "pending"
    audit(ctx.db, action="billing.checkout_created", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="subscription",
          entity_id=sub.id, meta={"plan": plan.code}, ip=client_ip(request))
    ctx.db.commit()
    return {"subscription_id": created["id"], "key_id": settings.razorpay_key_id, "plan": plan.code, "reused": False}


@router.post("/subscription/verify")
def verify(body: VerifySubscriptionIn, ctx: TenantContext = Depends(require_role(Role.owner))):
    """Checkout success callback. Verifies Razorpay's signature, then asks Razorpay for the real status."""
    client = _client()
    sub = _locked_sub(ctx)
    if sub.razorpay_subscription_id != body.razorpay_subscription_id:
        raise HTTPException(status_code=404, detail="Subscription not found")
    if not rz.verify_subscription_signature(body.razorpay_payment_id, body.razorpay_subscription_id, body.razorpay_signature):
        raise HTTPException(status_code=400, detail="Payment signature could not be verified")
    try:
        remote = client.fetch_subscription(sub.razorpay_subscription_id)
    except rz.RazorpayError:
        raise HTTPException(status_code=502, detail="Couldn't confirm the payment with Razorpay yet. It will update automatically.")
    before = svc.snapshot(sub)
    svc.sync_from_razorpay(ctx.db, sub, remote)
    svc.record_change(ctx.db, sub, before, source="user", ref=body.razorpay_payment_id)
    audit(ctx.db, action="billing.verified", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="subscription",
          entity_id=sub.id, meta={"razorpay_status": remote.get("status")})
    ctx.db.commit()
    return {"status": sub.status, "razorpay_status": remote.get("status"),
            "message": "Payment confirmed." if sub.status == "active" else "Payment authorised. Your plan activates when the first charge is confirmed."}


# ---------------- Prepaid plans: ONE Cashfree Payment Gateway payment for 1, 3, 6 or 12 months (no subscription, no mandate, nothing recurring) ----------------
def _prepaid_client():
    if not settings.prepaid_configured:
        raise HTTPException(status_code=503, detail={"code": "checkout_closed", "message": "Online payment for prepaid plans is not open yet."})
    try:
        return cashfree_svc.get_cashfree()
    except cashfree_svc.CashfreeNotConfigured:
        raise HTTPException(status_code=503, detail={"code": "checkout_closed", "message": "Online payment for prepaid plans is not open yet."})


@router.get("/prepaid/offers")
def prepaid_offers(ctx: TenantContext = Depends(get_tenant_context)):
    """Temporary prices that exist for THIS business only (usually none). Informational: the amount is decided by the server again when an order is created."""
    return {"offers": prepaid.offers_for(ctx.db, ctx.tenant_id)}


@router.post("/prepaid/checkout", dependencies=[Depends(limit_by_ip("prepaid-checkout", 12, 300))])
def prepaid_checkout(body: PrepaidCheckoutIn, request: Request, ctx: TenantContext = Depends(require_role(Role.owner))):
    """Creates a Cashfree order for a plan and a number of months and returns what the browser needs to open Cashfree's payment page. The amount is the SERVER's (services/plans.py); the
    request carries none. Nothing is granted here: access starts only when Cashfree reports the order paid (see /prepaid/verify and the webhook)."""
    ensure_verified(ctx.user)
    client = _prepaid_client()
    sub = _locked_sub(ctx)
    tenant = ctx.db.get(Tenant, ctx.tenant_id)
    try:
        out = prepaid.create_order(ctx.db, client, sub=sub, tenant=tenant, user=ctx.user, plan_code=body.plan, months=body.months, phone=body.phone)
    except prepaid.PrepaidError as exc:
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})
    ctx.db.commit()
    return out


@router.post("/prepaid/verify", dependencies=[Depends(limit_by_ip("prepaid-verify", 60, 300))])
def prepaid_verify(body: PrepaidVerifyIn, ctx: TenantContext = Depends(require_role(Role.owner))):
    """The return page's question: what really happened to this order? Answered by asking Cashfree from the server; nothing the browser says about the payment is used."""
    client = _prepaid_client()
    try:
        out = prepaid.verify(ctx.db, client, tenant_id=ctx.tenant_id, order_id=body.order_id)
    except prepaid.PrepaidError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=exc.status, detail={"code": exc.code, "message": exc.message})
    ctx.db.commit()
    return out


@router.post("/subscription/cancel")
def cancel(body: CancelIn, request: Request, ctx: TenantContext = Depends(require_role(Role.owner))):
    sub = _locked_sub(ctx)
    if settings.cashfree_enabled and sub.provider == "cashfree":
        cfb.cancel(ctx.db, _cf_client(), sub, user_id=ctx.user.id)
        audit(ctx.db, action="billing.cancel", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="subscription", entity_id=sub.id, meta={"provider": "cashfree"}, ip=client_ip(request))
        ctx.db.commit()
        return {"status": sub.status, "cancel_at_period_end": True, "access_until": sub.current_period_end}
    if not sub.razorpay_subscription_id or sub.status not in ("active", "past_due", "pending", "trialing"):
        raise HTTPException(status_code=409, detail="There is no paid subscription to cancel")
    client = _client()
    try:
        client.cancel_subscription(sub.razorpay_subscription_id, body.at_cycle_end)
    except rz.RazorpayError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=502, detail="Razorpay couldn't cancel the subscription. Please try again.")
    before = svc.snapshot(sub)
    sub.cancel_at_period_end = body.at_cycle_end
    if not body.at_cycle_end:
        sub.status, sub.canceled_at = "canceled", utcnow()
    svc.record_change(ctx.db, sub, before, source="user", kind="cancel_requested" if body.at_cycle_end else "canceled", meta={"at_cycle_end": body.at_cycle_end})
    audit(ctx.db, action="billing.cancel", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="subscription",
          entity_id=sub.id, meta={"at_cycle_end": body.at_cycle_end}, ip=client_ip(request))
    ctx.db.commit()
    return {"status": sub.status, "cancel_at_period_end": sub.cancel_at_period_end}


@router.post("/subscription/change-plan")
def change_plan(body: ChangePlanIn, request: Request, ctx: TenantContext = Depends(require_role(Role.owner))):
    ensure_verified(ctx.user)
    sub = _locked_sub(ctx)
    target = ctx.db.get(BillingPlan, body.plan)
    current = ctx.db.get(BillingPlan, sub.plan)
    if not target or not target.is_active:
        raise HTTPException(status_code=404, detail="Unknown plan")
    is_cf = settings.cashfree_enabled and sub.provider == "cashfree"
    if not is_cf and (not sub.razorpay_subscription_id or sub.status != "active"):
        raise HTTPException(status_code=409, detail="Start a subscription first (checkout), then you can change plans.")
    if current and current.code == target.code and not (is_cf and sub.pending_plan):
        raise HTTPException(status_code=409, detail="You're already on this plan")
    upgrade = current is None or target.price_paise > current.price_paise
    if not upgrade:  # downgrade guard: current usage must fit the smaller plan
        problems = []
        if ent.locations_used(ctx.db, ctx.tenant_id) > target.max_locations:
            problems.append(f"reduce active locations to {target.max_locations}")
        if ent.seats_used(ctx.db, ctx.tenant_id) > target.max_staff:
            problems.append(f"reduce team members to {target.max_staff}")
        if problems:
            raise HTTPException(status_code=409, detail={"code": "downgrade_blocked", "message": "Before downgrading, " + " and ".join(problems) + "."})
    if is_cf:
        out = cfb.change_plan(ctx.db, _cf_client(), sub, target, current)
        audit(ctx.db, action="billing.change_plan", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="subscription", entity_id=sub.id,
              meta={"to": target.code, "immediate": False, "provider": "cashfree"}, ip=client_ip(request))
        ctx.db.commit()
        return out
    client = _client()
    try:
        rzp_plan_id = svc.ensure_razorpay_plan(ctx.db, client, target)
        client.update_subscription(sub.razorpay_subscription_id, plan_id=rzp_plan_id, at_cycle_end=not upgrade)
    except rz.RazorpayError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=502, detail="Razorpay couldn't change the plan. Please try again.")
    before = svc.snapshot(sub)
    if upgrade:
        svc.apply_plan(sub, target)  # Razorpay accepted an immediate change
        sub.pending_plan = None
        svc.record_change(ctx.db, sub, before, source="user", kind="plan_changed", meta={"direction": "upgrade"})
    else:
        sub.pending_plan = target.code  # takes effect at the next cycle (webhook subscription.updated/charged)
        svc.log_event(ctx.db, ctx.tenant_id, "plan_change_scheduled", source="user", from_plan=sub.plan, to_plan=target.code, meta={"effective": "next cycle", "data_kept": True})
    audit(ctx.db, action="billing.change_plan", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="subscription",
          entity_id=sub.id, meta={"to": target.code, "immediate": upgrade}, ip=client_ip(request))
    ctx.db.commit()
    return {"plan": sub.plan, "pending_plan": sub.pending_plan}


@router.get("/subscription/preview")
def checkout_preview(plan: str = Query(pattern="^[a-z_]{3,32}$"), ctx: TenantContext = Depends(require_role(Role.owner))):
    """What the customer is told BEFORE Cashfree opens: the plan, the monthly amount, the refundable authorisation, the first payment date. Creates nothing and calls nobody."""
    if not settings.cashfree_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    sub = ctx.db.scalar(select(Subscription).where(Subscription.tenant_id == ctx.tenant_id))
    p = ctx.db.get(BillingPlan, plan)
    if sub is None or not p or not p.is_active:
        raise HTTPException(status_code=404, detail="Unknown plan")
    return {**cfb.disclosure(ctx.db, sub, p), "trial_days": settings.trial_days, "trial_starts_on_authorization": bool(sub.status == "incomplete")}


@router.post("/subscription/retry-payment", dependencies=[Depends(limit_by_ip("cf-retry", 10, 300))])
def retry_payment(ctx: TenantContext = Depends(require_role(Role.owner))):
    """Ask Cashfree to retry a failed CARD payment. UPI AutoPay retries by itself. Cashfree's own call, at most 3 a cycle: FlowQR never creates a charge."""
    if not settings.cashfree_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    sub = _locked_sub(ctx)
    if sub.status != "past_due":
        raise HTTPException(status_code=409, detail="There is no failed payment to retry")
    try:
        asked = cfb.retry_now(ctx.db, _cf_client(), sub)
    except cashfree_svc.CashfreeError:
        ctx.db.rollback()
        raise HTTPException(status_code=502, detail="We couldn't reach the payment provider. Please try again.")
    ctx.db.commit()
    return {"requested": asked, "message": "We asked your bank to try the payment again." if asked else "A retry isn't possible right now (UPI payments retry automatically, a card can be retried once a day, up to 3 times)."}


@router.post("/subscription/sync", dependencies=[Depends(limit_by_ip("cf-sync", 30, 60))])
def sync_subscription(ctx: TenantContext = Depends(require_role(Role.owner))):
    """Cashfree: called by the checkout return page. It never reads what the browser says happened: it asks Cashfree for the subscription and its payments and applies the answer."""
    if not settings.cashfree_enabled:
        raise HTTPException(status_code=404, detail="Not found")
    sub = _locked_sub(ctx)
    if not sub.cashfree_subscription_id:
        raise HTTPException(status_code=404, detail="No payment setup found")
    try:
        out = cfb.sync(ctx.db, _cf_client(), sub, source="user")
    except cashfree_svc.CashfreeError:
        ctx.db.rollback()
        raise HTTPException(status_code=502, detail="We couldn't confirm this with the payment provider yet. It will update automatically.")
    audit(ctx.db, action="billing.synced", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="subscription", entity_id=sub.id, meta={"status": sub.status})
    ctx.db.commit()
    return {"status": sub.status, "billing_state": cfb.billing_state(sub), "authorization_status": sub.authorization_status, **out}


@router.get("/subscription/status")
def subscription_status(ctx: TenantContext = Depends(get_tenant_context)):
    """Read-only and cheap: what we currently know (the page polls this while a bank approval is pending)."""
    sub = ctx.db.scalar(select(Subscription).where(Subscription.tenant_id == ctx.tenant_id))
    e = ent.for_tenant(ctx.db, ctx.tenant_id)
    return {"status": e.status, "active": e.active, "billing_state": cfb.billing_state(sub), "authorization_status": sub.authorization_status if sub else None,
            "first_charge_at": sub.first_charge_at if sub else None, "next_charge_at": sub.next_charge_at if sub else None}


@router.get("/payments", response_model=list[PaymentOut])
def payments(ctx: TenantContext = Depends(get_tenant_context), kind: str | None = Query(None, pattern="^(subscription|card_order)$"),
             limit: int = Query(50, ge=1, le=200)):
    q = select(Payment).where(Payment.tenant_id == ctx.tenant_id)
    if kind:
        q = q.where(Payment.kind == kind)
    return ctx.db.scalars(q.order_by(Payment.created_at.desc()).limit(limit)).all()


# ---------------- Physical card orders (separate from subscriptions) ----------------

@router.get("/card-orders", response_model=list[CardOrderOut])
def card_orders(ctx: TenantContext = Depends(get_tenant_context)):
    return ctx.db.scalars(select(CardOrder).where(CardOrder.tenant_id == ctx.tenant_id).order_by(CardOrder.created_at.desc())).all()


@router.post("/card-orders", status_code=201)
def create_card_order(body: CardOrderIn, request: Request, ctx: TenantContext = Depends(require_role(Role.owner)),
                      idempotency_key: str | None = Header(default=None, max_length=80)):
    ensure_verified(ctx.user)
    offer = svc.card_offer_for(body.quantity)  # the confirmed bundles (1 card, 2 cards) are priced as bundles, not per card
    if offer is None:
        if not settings.card_price_paise:
            raise HTTPException(status_code=503, detail={"code": "card_pricing_not_configured", "message": "Card ordering isn't open yet: card pricing hasn't been configured."})
        if not (settings.card_order_min_qty <= body.quantity <= settings.card_order_max_qty):
            bundles = " or ".join(str(o["quantity"]) for o in (settings.card_offers or []))
            raise HTTPException(status_code=422, detail=f"Order {bundles} cards, or between {settings.card_order_min_qty} and {settings.card_order_max_qty}.")
    if idempotency_key:
        prior = ctx.db.scalar(select(CardOrder).where(CardOrder.tenant_id == ctx.tenant_id, CardOrder.idempotency_key == idempotency_key))
        if prior:  # same request replayed: return the same order instead of creating another
            return {"order_id": prior.razorpay_order_id, "key_id": settings.razorpay_key_id, "amount_paise": prior.amount_paise,
                    "card_order_id": str(prior.id), "reused": True}
    client = _client()
    amount = offer["price_paise"] if offer else body.quantity * settings.card_price_paise
    order = CardOrder(tenant_id=ctx.tenant_id, quantity=body.quantity, unit_price_paise=amount // body.quantity, amount_paise=amount, offer_code=offer["code"] if offer else None,
                      shipping=body.shipping.model_dump(), idempotency_key=idempotency_key, created_by=ctx.user.id)
    ctx.db.add(order)
    ctx.db.flush()
    try:
        created = client.create_order(amount_paise=amount, receipt=f"card-{order.id.hex[:16]}", notes={"tenant_id": str(ctx.tenant_id), "card_order_id": str(order.id)})
    except rz.RazorpayError:
        ctx.db.rollback()
        raise HTTPException(status_code=502, detail="Payment provider error. Please try again.")
    order.razorpay_order_id = created["id"]
    audit(ctx.db, action="billing.card_order_created", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="card_order",
          entity_id=order.id, meta={"quantity": body.quantity}, ip=client_ip(request))
    ctx.db.commit()
    return {"order_id": order.razorpay_order_id, "key_id": settings.razorpay_key_id, "amount_paise": amount,
            "card_order_id": str(order.id), "reused": False}


@router.post("/card-orders/verify")
def verify_card_order(body: VerifyOrderIn, ctx: TenantContext = Depends(require_role(Role.owner))):
    order = ctx.db.scalar(select(CardOrder).where(CardOrder.razorpay_order_id == body.razorpay_order_id, CardOrder.tenant_id == ctx.tenant_id).with_for_update())
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if not rz.verify_order_signature(body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature):
        raise HTTPException(status_code=400, detail="Payment signature could not be verified")
    client = _client()
    try:
        remote = client.fetch_order(order.razorpay_order_id)
    except rz.RazorpayError:
        raise HTTPException(status_code=502, detail="Couldn't confirm the payment with Razorpay yet. It will update automatically.")
    if remote.get("status") == "paid" and int(remote.get("amount_paid", 0)) >= order.amount_paise:
        svc.mark_card_order_paid(ctx.db, order)
        svc.upsert_payment(ctx.db, tenant_id=ctx.tenant_id, kind="card_order", card_order_id=order.id,
                           entity={"id": body.razorpay_payment_id, "amount": order.amount_paise, "currency": "INR", "status": "captured",
                                   "order_id": order.razorpay_order_id})
    ctx.db.commit()
    return {"status": order.status}


# ---------------- Webhook ----------------

@router.post("/razorpay/webhook", dependencies=[Depends(limit_by_ip("rzp-webhook", 300, 60))])
async def razorpay_webhook(request: Request, x_razorpay_signature: str | None = Header(default=None),
                           x_razorpay_event_id: str | None = Header(default=None), db: Session = Depends(get_db)):
    raw = await request.body()
    if not rz.verify_webhook_signature(raw, x_razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid signature")
    try:
        event = json.loads(raw)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    import hashlib
    event_id = x_razorpay_event_id or hashlib.sha256(raw).hexdigest()
    set_rls_context(db, bypass=True)
    row = svc.record_event(db, event_id, event.get("event", ""))
    if row is None:
        return {"status": "duplicate"}  # already handled: acknowledge so Razorpay stops retrying
    try:
        result = svc.process_webhook(db, event, event_id)
        row.status, row.processed_at = result, utcnow()
        db.commit()
    except Exception:
        db.rollback()
        log.exception("Razorpay webhook processing failed (event %s)", event_id)
        raise HTTPException(status_code=500, detail="Processing failed")  # non-2xx => Razorpay retries
    return {"status": result}
