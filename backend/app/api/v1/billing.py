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
from app.models import BillingPlan, CardOrder, Payment, Role, Subscription
from app.models.base import utcnow
from app.schemas.billing import (
    CancelIn, CardOrderIn, CardOrderOut, ChangePlanIn, CheckoutIn, PaymentOut, PlanOut, VerifyOrderIn, VerifySubscriptionIn,
)
from app.services import billing as svc
from app.services import entitlements as ent
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


def _config() -> dict:
    return {"configured": settings.razorpay_configured, "mode": settings.razorpay_mode,
            "key_id": settings.razorpay_key_id if settings.razorpay_configured else None}


@router.get("/plans")
def plans(db: Session = Depends(get_db)):
    """Public: used by the pricing page."""
    set_rls_context(db, bypass=True)
    rows = db.scalars(select(BillingPlan).where(BillingPlan.is_active.is_(True)).order_by(BillingPlan.sort_order)).all()
    return {"plans": [PlanOut.model_validate(p) for p in rows], "trial_days": settings.trial_days,
            "billing": _config(), "card_price_paise": settings.card_price_paise, "card_ordering_enabled": bool(settings.card_price_paise) and settings.razorpay_configured}


@router.get("/subscription")
def subscription(ctx: TenantContext = Depends(get_tenant_context)):
    sub = ctx.db.scalar(select(Subscription).where(Subscription.tenant_id == ctx.tenant_id))
    e = ent.compute(sub)
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
        "limits": {"locations": e.max_locations, "ai_generations": e.monthly_ai_generations, "staff": e.max_staff, "features": sorted(e.features)},
        "usage": {"locations": ent.locations_used(ctx.db, ctx.tenant_id), "ai_generations": usage_this_month(ctx.db, ctx.tenant_id),
                  "staff": ent.seats_used(ctx.db, ctx.tenant_id)},
    }


def _locked_sub(ctx: TenantContext) -> Subscription:
    sub = ctx.db.scalar(select(Subscription).where(Subscription.tenant_id == ctx.tenant_id).with_for_update())
    if not sub:
        raise HTTPException(status_code=404, detail="No subscription found")
    return sub


@router.post("/subscription/checkout")
def checkout(body: CheckoutIn, request: Request, ctx: TenantContext = Depends(require_role(Role.owner))):
    """Creates (or re-uses) a Razorpay subscription for the chosen plan. Idempotent per tenant+plan."""
    ensure_verified(ctx.user)
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
        if sub.status == "trialing" and sub.trial_ends_at and sub.trial_ends_at > utcnow() + __import__("datetime").timedelta(minutes=10):
            start_at = int(sub.trial_ends_at.timestamp())  # no charge until the trial ends
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
    svc.sync_from_razorpay(ctx.db, sub, remote)
    audit(ctx.db, action="billing.verified", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="subscription",
          entity_id=sub.id, meta={"razorpay_status": remote.get("status")})
    ctx.db.commit()
    return {"status": sub.status, "razorpay_status": remote.get("status"),
            "message": "Payment confirmed." if sub.status == "active" else "Payment authorised. Your plan activates when the first charge is confirmed."}


@router.post("/subscription/cancel")
def cancel(body: CancelIn, request: Request, ctx: TenantContext = Depends(require_role(Role.owner))):
    sub = _locked_sub(ctx)
    if not sub.razorpay_subscription_id or sub.status not in ("active", "past_due", "pending", "trialing"):
        raise HTTPException(status_code=409, detail="There is no paid subscription to cancel")
    client = _client()
    try:
        client.cancel_subscription(sub.razorpay_subscription_id, body.at_cycle_end)
    except rz.RazorpayError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=502, detail="Razorpay couldn't cancel the subscription. Please try again.")
    sub.cancel_at_period_end = body.at_cycle_end
    if not body.at_cycle_end:
        sub.status, sub.canceled_at = "canceled", utcnow()
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
    if not sub.razorpay_subscription_id or sub.status != "active":
        raise HTTPException(status_code=409, detail="Start a subscription first (checkout), then you can change plans.")
    if current and current.code == target.code:
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
    client = _client()
    try:
        rzp_plan_id = svc.ensure_razorpay_plan(ctx.db, client, target)
        client.update_subscription(sub.razorpay_subscription_id, plan_id=rzp_plan_id, at_cycle_end=not upgrade)
    except rz.RazorpayError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=502, detail="Razorpay couldn't change the plan. Please try again.")
    if upgrade:
        svc.apply_plan(sub, target)  # Razorpay accepted an immediate change
        sub.pending_plan = None
    else:
        sub.pending_plan = target.code  # takes effect at the next cycle (webhook subscription.updated/charged)
    audit(ctx.db, action="billing.change_plan", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="subscription",
          entity_id=sub.id, meta={"to": target.code, "immediate": upgrade}, ip=client_ip(request))
    ctx.db.commit()
    return {"plan": sub.plan, "pending_plan": sub.pending_plan}


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
    if not settings.card_price_paise:
        raise HTTPException(status_code=503, detail={"code": "card_pricing_not_configured", "message": "Card ordering isn't open yet: card pricing hasn't been configured."})
    if not (settings.card_order_min_qty <= body.quantity <= settings.card_order_max_qty):
        raise HTTPException(status_code=422, detail=f"Order between {settings.card_order_min_qty} and {settings.card_order_max_qty} cards")
    if idempotency_key:
        prior = ctx.db.scalar(select(CardOrder).where(CardOrder.tenant_id == ctx.tenant_id, CardOrder.idempotency_key == idempotency_key))
        if prior:  # same request replayed: return the same order instead of creating another
            return {"order_id": prior.razorpay_order_id, "key_id": settings.razorpay_key_id, "amount_paise": prior.amount_paise,
                    "card_order_id": str(prior.id), "reused": True}
    client = _client()
    amount = body.quantity * settings.card_price_paise
    order = CardOrder(tenant_id=ctx.tenant_id, quantity=body.quantity, unit_price_paise=settings.card_price_paise, amount_paise=amount,
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
