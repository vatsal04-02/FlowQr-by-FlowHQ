"""Platform-admin (FlowHQ staff) endpoints: card inventory, batches, tenants overview."""
import csv
import html
import io
import uuid
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from datetime import timedelta

from sqlalchemy import func, or_, select, update

from app.api.v1.cards import card_out
from app.core.deps import AuthContext, require_platform_admin
from app.core.rate_limit import client_ip
from app.models import (
    CardAssignment, CardBatch, CardStatus, Location, Membership, QRCard, Review, ScanEvent, ScanEventType, Tenant,
)
from app.models import (
    AIGenerationLog, AuditLog, AuthSession, BillingPlan, CardOrder, Payment, Subscription, User,
)
from app.models.base import utcnow
from app.models.tenancy import Membership as _M, Role as _R
from app.schemas.admin import CardOrderAdminIn, SubscriptionAdminIn, SuspendIn, SupportIn, UserActiveIn
from app.services import billing as billing_svc
from app.services.ai_usage import month_start
from app.schemas.cards import AssignIn, BatchCreateIn, BatchOut, CardOut, StatusIn
from app.services import cards as svc
from app.services.audit import audit
from app.services.qr import card_url, qr_png, qr_svg

router = APIRouter(prefix="/admin", tags=["platform-admin"])


@router.post("/batches", response_model=BatchOut, status_code=201)
def create_batch(body: BatchCreateIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    batch = svc.create_batch(ctx.db, name=body.name, quantity=body.quantity, prefix=body.prefix,
                             created_by=ctx.user.id, notes=body.notes)
    audit(ctx.db, action="admin.batch_create", user_id=ctx.user.id, entity_type="batch", entity_id=batch.id,
          meta={"quantity": body.quantity, "prefix": body.prefix}, ip=client_ip(request))
    ctx.db.commit()
    return batch


@router.get("/batches", response_model=list[BatchOut])
def list_batches(ctx: AuthContext = Depends(require_platform_admin)):
    return ctx.db.scalars(select(CardBatch).order_by(CardBatch.created_at.desc())).all()


def _batch_cards(ctx: AuthContext, batch_id: uuid.UUID) -> tuple[CardBatch, list[QRCard]]:
    batch = ctx.db.get(CardBatch, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")
    cards = ctx.db.scalars(select(QRCard).where(QRCard.batch_id == batch_id).order_by(QRCard.card_code)).all()
    return batch, list(cards)


@router.get("/batches/{batch_id}/export.zip")
def export_batch_zip(batch_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """ZIP with one print-quality PNG + SVG per card and a manifest.csv (card code -> URL for NFC encoding)."""
    batch, cards = _batch_cards(ctx, batch_id)
    buf = io.BytesIO()
    manifest = io.StringIO()
    w = csv.writer(manifest)
    w.writerow(["card_code", "url", "status"])
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for c in cards:
            url = card_url(c.public_token)
            z.writestr(f"png/{c.card_code}.png", qr_png(url, scale=16))
            z.writestr(f"svg/{c.card_code}.svg", qr_svg(url))
            w.writerow([c.card_code, url, c.status.value])
        z.writestr("manifest.csv", manifest.getvalue())
    audit(ctx.db, action="admin.batch_export", user_id=ctx.user.id, entity_type="batch", entity_id=batch.id,
          ip=client_ip(request))
    ctx.db.commit()
    return Response(buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{batch.prefix}-batch-{batch.id.hex[:8]}.zip"'})


@router.get("/batches/{batch_id}/sheet", response_class=Response)
def printable_sheet(batch_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    """Printable A4 sheet (open and Ctrl+P). 3 columns of QR cards with the card code underneath."""
    batch, cards = _batch_cards(ctx, batch_id)
    cells = []
    for c in cards:
        svg = qr_svg(card_url(c.public_token), scale=4).decode()
        cells.append(
            f'<div class="cell">{svg}<div class="code">{html.escape(c.card_code)}</div>'
            f'<div class="brand">FlowQR by FlowHQ</div></div>'
        )
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(batch.name)} - print sheet</title>
<style>
@page {{ size: A4; margin: 10mm; }}
body {{ font-family: system-ui, sans-serif; margin: 0; }}
h1 {{ font-size: 14px; margin: 0 0 8px; }}
.grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 6mm; }}
.cell {{ border: 1px dashed #bbb; padding: 4mm; text-align: center; break-inside: avoid; }}
.cell svg {{ width: 48mm; height: 48mm; }}
.code {{ font-weight: 700; font-size: 14px; margin-top: 2mm; letter-spacing: .06em; }}
.brand {{ font-size: 9px; color: #666; }}
@media print {{ h1 {{ display: none; }} }}
</style></head><body><h1>{html.escape(batch.name)} - {len(cards)} cards. Press Ctrl+P to print.</h1>
<div class="grid">{''.join(cells)}</div></body></html>"""
    return Response(page, media_type="text/html; charset=utf-8", headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:"})


@router.get("/cards")
def list_cards(
    ctx: AuthContext = Depends(require_platform_admin),
    search: str | None = None,
    status: CardStatus | None = None,
    tenant_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    q = select(QRCard)
    if search:
        q = q.where(QRCard.card_code.ilike(f"%{search.strip()}%"))
    if status:
        q = q.where(QRCard.status == status)
    if tenant_id:
        q = q.where(QRCard.tenant_id == tenant_id)
    if batch_id:
        q = q.where(QRCard.batch_id == batch_id)
    total = ctx.db.scalar(select(func.count()).select_from(q.subquery()))
    cards = ctx.db.scalars(q.order_by(QRCard.card_code).limit(limit).offset(offset)).all()
    tenants = {t.id: t.name for t in ctx.db.scalars(select(Tenant).where(Tenant.id.in_([c.tenant_id for c in cards if c.tenant_id])))}
    locs = {l.id: l.name for l in ctx.db.scalars(select(Location).where(Location.id.in_([c.location_id for c in cards if c.location_id])))}
    counts = svc.card_scan_counts(ctx.db, [c.id for c in cards])
    last = svc.card_last_scans(ctx.db, [c.id for c in cards])
    return {
        "total": total,
        "items": [card_out(c, stats=counts.get(c.id), tenant_name=tenants.get(c.tenant_id), location_name=locs.get(c.location_id), last_scan_at=last.get(c.id)) for c in cards],
    }


def _card_or_404(ctx: AuthContext, card_id: uuid.UUID) -> QRCard:
    card = ctx.db.get(QRCard, card_id)
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


@router.get("/cards/{card_id}")
def card_detail(card_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    card = _card_or_404(ctx, card_id)
    history = ctx.db.execute(
        select(CardAssignment, Tenant.name, Location.name)
        .join(Tenant, Tenant.id == CardAssignment.tenant_id)
        .outerjoin(Location, Location.id == CardAssignment.location_id)
        .where(CardAssignment.card_id == card.id).order_by(CardAssignment.assigned_at.desc())
    ).all()
    tenant = ctx.db.get(Tenant, card.tenant_id) if card.tenant_id else None
    loc = ctx.db.get(Location, card.location_id) if card.location_id else None
    return {
        "card": card_out(card, stats=svc.card_scan_counts(ctx.db, [card.id]).get(card.id),
                         tenant_name=tenant.name if tenant else None, location_name=loc.name if loc else None),
        "history": [{"tenant": t, "location": l, "assigned_at": a.assigned_at, "unassigned_at": a.unassigned_at} for a, t, l in history],
    }


@router.post("/cards/{card_id}/assign", response_model=CardOut)
def assign(card_id: uuid.UUID, body: AssignIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    card = _card_or_404(ctx, card_id)
    tenant = ctx.db.get(Tenant, body.tenant_id)
    location = ctx.db.get(Location, body.location_id)
    if not tenant or not location:
        raise HTTPException(status_code=404, detail="Business or location not found")
    if card.status == CardStatus.lost:
        raise HTTPException(status_code=400, detail="Card is marked lost; set status first")
    svc.assign_card(ctx.db, card, tenant=tenant, location=location, by=ctx.user.id)
    if body.label is not None:
        card.label = body.label
    audit(ctx.db, action="admin.card_assign", tenant_id=tenant.id, user_id=ctx.user.id, entity_type="card",
          entity_id=card.id, meta={"location_id": str(location.id)}, ip=client_ip(request))
    ctx.db.commit()
    return card_out(card, tenant_name=tenant.name, location_name=location.name)


@router.post("/cards/{card_id}/unassign", response_model=CardOut)
def unassign(card_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    card = _card_or_404(ctx, card_id)
    old_tenant = card.tenant_id
    svc.unassign_card(ctx.db, card)
    audit(ctx.db, action="admin.card_unassign", tenant_id=old_tenant, user_id=ctx.user.id, entity_type="card",
          entity_id=card.id, ip=client_ip(request))
    ctx.db.commit()
    return card_out(card)


@router.post("/cards/{card_id}/status", response_model=CardOut)
def set_status(card_id: uuid.UUID, body: StatusIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    card = _card_or_404(ctx, card_id)
    if body.status in (CardStatus.assigned, CardStatus.active) and not card.tenant_id:
        raise HTTPException(status_code=400, detail="Assign the card to a location first")
    if body.status == CardStatus.unassigned:
        raise HTTPException(status_code=400, detail="Use the unassign action")
    card.status = body.status
    audit(ctx.db, action="admin.card_status", tenant_id=card.tenant_id, user_id=ctx.user.id, entity_type="card",
          entity_id=card.id, meta={"status": body.status.value}, ip=client_ip(request))
    ctx.db.commit()
    return card_out(card)


@router.get("/cards/{card_id}/qr.{fmt}")
def admin_card_qr(card_id: uuid.UUID, fmt: str, ctx: AuthContext = Depends(require_platform_admin)):
    card = _card_or_404(ctx, card_id)
    url = card_url(card.public_token)
    if fmt == "png":
        return Response(qr_png(url), media_type="image/png", headers={"Content-Disposition": f'attachment; filename="{card.card_code}.png"'})
    if fmt == "svg":
        return Response(qr_svg(url), media_type="image/svg+xml", headers={"Content-Disposition": f'attachment; filename="{card.card_code}.svg"'})
    raise HTTPException(status_code=404, detail="Unsupported format")


def _tenant_row(db, t: Tenant, sub: Subscription | None, owner_email: str | None) -> dict:
    return {
        "id": t.id, "name": t.name, "category": t.category, "created_at": t.created_at, "is_active": t.is_active,
        "suspended_at": t.suspended_at, "suspension_reason": t.suspension_reason, "support_status": t.support_status,
        "owner_email": owner_email, "plan": sub.plan if sub else None, "subscription_status": sub.status if sub else None,
        "locations": db.scalar(select(func.count()).select_from(Location).where(Location.tenant_id == t.id)),
        "cards": db.scalar(select(func.count()).select_from(QRCard).where(QRCard.tenant_id == t.id)),
        "members": db.scalar(select(func.count()).select_from(Membership).where(Membership.tenant_id == t.id)),
    }


@router.get("/tenants")
def list_tenants(ctx: AuthContext = Depends(require_platform_admin), search: str | None = None, status: str | None = None,
                 limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
    q = select(Tenant)
    if search:
        q = q.where(Tenant.name.ilike(f"%{search.strip()}%"))
    if status == "suspended":
        q = q.where(Tenant.is_active.is_(False))
    elif status in ("trialing", "active", "past_due", "halted", "expired", "canceled", "pending"):
        q = q.where(Tenant.id.in_(select(Subscription.tenant_id).where(Subscription.status == status)))
    total = ctx.db.scalar(select(func.count()).select_from(q.subquery()))
    tenants = ctx.db.scalars(q.order_by(Tenant.created_at.desc()).limit(limit).offset(offset)).all()
    subs = {x.tenant_id: x for x in ctx.db.scalars(select(Subscription).where(Subscription.tenant_id.in_([t.id for t in tenants])))}
    owners = dict(ctx.db.execute(select(_M.tenant_id, User.email).join(User, User.id == _M.user_id).where(_M.role == _R.owner, _M.tenant_id.in_([t.id for t in tenants]))).all())
    rows = [_tenant_row(ctx.db, t, subs.get(t.id), owners.get(t.id)) for t in tenants]
    return {"total": total, "items": rows}


@router.get("/tenants/{tenant_id}/locations")
def tenant_locations(tenant_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    locs = ctx.db.scalars(select(Location).where(Location.tenant_id == tenant_id, Location.is_active.is_(True)).order_by(Location.name)).all()
    return [{"id": l.id, "name": l.name, "city": l.city} for l in locs]


def _tenant_or_404(ctx: AuthContext, tenant_id: uuid.UUID) -> Tenant:
    t = ctx.db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail="Business not found")
    return t


@router.get("/tenants/{tenant_id}")
def tenant_detail(tenant_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    t = _tenant_or_404(ctx, tenant_id)
    db = ctx.db
    sub = db.scalar(select(Subscription).where(Subscription.tenant_id == t.id))
    members = db.execute(select(_M, User).join(User, User.id == _M.user_id).where(_M.tenant_id == t.id)).all()
    locs = db.scalars(select(Location).where(Location.tenant_id == t.id)).all()
    cards = db.scalars(select(QRCard).where(QRCard.tenant_id == t.id).order_by(QRCard.card_code)).all()
    pays = db.scalars(select(Payment).where(Payment.tenant_id == t.id).order_by(Payment.created_at.desc()).limit(25)).all()
    audit_rows = db.scalars(select(AuditLog).where(AuditLog.tenant_id == t.id).order_by(AuditLog.created_at.desc()).limit(25)).all()
    ai_month = db.scalar(select(func.count()).select_from(AIGenerationLog).where(AIGenerationLog.tenant_id == t.id, AIGenerationLog.created_at >= month_start())) or 0
    return {
        "tenant": _tenant_row(db, t, sub, next((u.email for m, u in members if m.role == _R.owner), None)) | {"support_note": t.support_note, "email": t.email, "phone": t.phone},
        "subscription": None if not sub else {c: getattr(sub, c) for c in ("plan", "status", "source", "max_locations", "monthly_ai_generations", "max_staff", "features",
                                                                           "trial_ends_at", "current_period_end", "cancel_at_period_end", "past_due_since", "razorpay_subscription_id")},
        "members": [{"user_id": u.id, "email": u.email, "full_name": u.full_name, "role": m.role.value, "is_active": u.is_active, "email_verified": bool(u.email_verified_at)} for m, u in members],
        "locations": [{"id": l.id, "name": l.name, "city": l.city, "is_active": l.is_active, "has_review_link": bool(l.review_url)} for l in locs],
        "cards": [{"id": c.id, "card_code": c.card_code, "status": c.status.value, "location_id": c.location_id} for c in cards],
        "payments": [{"id": p.id, "kind": p.kind, "status": p.status, "amount_paise": p.amount_paise, "created_at": p.created_at} for p in pays],
        "audit": [{"action": a.action, "created_at": a.created_at, "user_id": a.user_id, "meta": a.meta} for a in audit_rows],
        "ai_generations_this_month": ai_month,
    }


@router.post("/tenants/{tenant_id}/suspend", status_code=204)
def suspend(tenant_id: uuid.UUID, body: SuspendIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    t = _tenant_or_404(ctx, tenant_id)
    t.is_active, t.suspended_at, t.suspension_reason = False, utcnow(), body.reason
    audit(ctx.db, action="admin.tenant_suspend", tenant_id=t.id, user_id=ctx.user.id, entity_type="tenant", entity_id=t.id, meta={"reason": body.reason}, ip=client_ip(request))
    ctx.db.commit()


@router.post("/tenants/{tenant_id}/unsuspend", status_code=204)
def unsuspend(tenant_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    t = _tenant_or_404(ctx, tenant_id)
    t.is_active, t.suspended_at, t.suspension_reason = True, None, None
    audit(ctx.db, action="admin.tenant_unsuspend", tenant_id=t.id, user_id=ctx.user.id, entity_type="tenant", entity_id=t.id, ip=client_ip(request))
    ctx.db.commit()


@router.patch("/tenants/{tenant_id}/support", status_code=204)
def support(tenant_id: uuid.UUID, body: SupportIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    t = _tenant_or_404(ctx, tenant_id)
    t.support_status, t.support_note = body.status, body.note
    audit(ctx.db, action="admin.support_status", tenant_id=t.id, user_id=ctx.user.id, entity_type="tenant", entity_id=t.id, meta={"status": body.status}, ip=client_ip(request))
    ctx.db.commit()


@router.patch("/users/{user_id}", status_code=204)
def set_user_active(user_id: uuid.UUID, body: UserActiveIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    u = ctx.db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    if u.id == ctx.user.id:
        raise HTTPException(status_code=400, detail="You can't deactivate yourself")
    u.is_active = body.is_active
    if not body.is_active:  # kill live sessions immediately
        ctx.db.execute(update(AuthSession).where(AuthSession.user_id == u.id, AuthSession.revoked_at.is_(None)).values(revoked_at=utcnow()))
    audit(ctx.db, action="admin.user_active", user_id=ctx.user.id, entity_type="user", entity_id=u.id, meta={"is_active": body.is_active}, ip=client_ip(request))
    ctx.db.commit()


@router.post("/tenants/{tenant_id}/subscription")
def manage_subscription(tenant_id: uuid.UUID, body: SubscriptionAdminIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Manual override (comps, extended trials, corrections). Does not touch Razorpay: a live Razorpay subscription keeps billing."""
    t = _tenant_or_404(ctx, tenant_id)
    sub = ctx.db.scalar(select(Subscription).where(Subscription.tenant_id == t.id).with_for_update())
    if not sub:
        raise HTTPException(status_code=404, detail="No subscription")
    if body.plan:
        plan = ctx.db.get(BillingPlan, body.plan)
        billing_svc.apply_plan(sub, plan)
    if body.status:
        sub.status = body.status
        if body.status in ("manual", "active") and not sub.razorpay_subscription_id:
            sub.source = "manual"
        if body.status != "trialing":
            sub.past_due_since = None
    if body.extend_trial_days:
        base = max(sub.trial_ends_at or utcnow(), utcnow())
        sub.trial_ends_at = base + timedelta(days=body.extend_trial_days)
        sub.status = "trialing" if not body.status else body.status
    audit(ctx.db, action="admin.subscription_override", tenant_id=t.id, user_id=ctx.user.id, entity_type="subscription", entity_id=sub.id,
          meta={"plan": body.plan, "status": body.status, "extend_trial_days": body.extend_trial_days, "note": body.note,
                "razorpay_live": bool(sub.razorpay_subscription_id)}, ip=client_ip(request))
    ctx.db.commit()
    return {"plan": sub.plan, "status": sub.status, "trial_ends_at": sub.trial_ends_at, "source": sub.source}


@router.get("/subscriptions")
def subscriptions(ctx: AuthContext = Depends(require_platform_admin), status: str | None = None, plan: str | None = None,
                  limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
    q = select(Subscription, Tenant.name).join(Tenant, Tenant.id == Subscription.tenant_id)
    if status:
        q = q.where(Subscription.status == status)
    if plan:
        q = q.where(Subscription.plan == plan)
    rows = ctx.db.execute(q.order_by(Subscription.created_at.desc()).limit(limit).offset(offset)).all()
    return [{"tenant_id": s.tenant_id, "tenant": name, "plan": s.plan, "status": s.status, "source": s.source, "trial_ends_at": s.trial_ends_at,
             "current_period_end": s.current_period_end, "cancel_at_period_end": s.cancel_at_period_end, "razorpay_subscription_id": s.razorpay_subscription_id} for s, name in rows]


@router.get("/payments")
def all_payments(ctx: AuthContext = Depends(require_platform_admin), kind: str | None = None, status: str | None = None,
                 tenant_id: uuid.UUID | None = None, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
    q = select(Payment, Tenant.name).join(Tenant, Tenant.id == Payment.tenant_id)
    if kind:
        q = q.where(Payment.kind == kind)
    if status:
        q = q.where(Payment.status == status)
    if tenant_id:
        q = q.where(Payment.tenant_id == tenant_id)
    rows = ctx.db.execute(q.order_by(Payment.created_at.desc()).limit(limit).offset(offset)).all()
    return [{"id": p.id, "tenant_id": p.tenant_id, "tenant": name, "kind": p.kind, "status": p.status, "amount_paise": p.amount_paise,
             "razorpay_payment_id": p.razorpay_payment_id, "error_description": p.error_description, "created_at": p.created_at, "paid_at": p.paid_at} for p, name in rows]


@router.get("/card-orders")
def all_card_orders(ctx: AuthContext = Depends(require_platform_admin), status: str | None = None, limit: int = Query(100, ge=1, le=200)):
    q = select(CardOrder, Tenant.name).join(Tenant, Tenant.id == CardOrder.tenant_id)
    if status:
        q = q.where(CardOrder.status == status)
    rows = ctx.db.execute(q.order_by(CardOrder.created_at.desc()).limit(limit)).all()
    return [{"id": o.id, "tenant_id": o.tenant_id, "tenant": name, "quantity": o.quantity, "amount_paise": o.amount_paise, "status": o.status,
             "shipping": o.shipping, "tracking_note": o.tracking_note, "created_at": o.created_at} for o, name in rows]


@router.patch("/card-orders/{order_id}")
def update_card_order(order_id: uuid.UUID, body: CardOrderAdminIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    o = ctx.db.get(CardOrder, order_id)
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    if o.status not in ("paid", "processing", "shipped") and body.status != "cancelled":
        raise HTTPException(status_code=409, detail="Only paid orders can be fulfilled")  # never ship before Razorpay confirmed payment
    o.status = body.status
    o.tracking_note = body.tracking_note or o.tracking_note
    audit(ctx.db, action="admin.card_order_update", tenant_id=o.tenant_id, user_id=ctx.user.id, entity_type="card_order", entity_id=o.id, meta={"status": body.status}, ip=client_ip(request))
    ctx.db.commit()
    return {"status": o.status}


@router.get("/ai-usage")
def ai_usage(ctx: AuthContext = Depends(require_platform_admin)):
    rows = ctx.db.execute(
        select(Tenant.id, Tenant.name, func.count(AIGenerationLog.id), func.count(AIGenerationLog.id).filter(AIGenerationLog.status != "ok"), Subscription.monthly_ai_generations)
        .select_from(Tenant).outerjoin(AIGenerationLog, (AIGenerationLog.tenant_id == Tenant.id) & (AIGenerationLog.created_at >= month_start()))
        .outerjoin(Subscription, Subscription.tenant_id == Tenant.id).group_by(Tenant.id, Tenant.name, Subscription.monthly_ai_generations)
        .order_by(func.count(AIGenerationLog.id).desc())).all()
    return [{"tenant_id": i, "tenant": n, "generations": c, "errors": int(e), "monthly_limit": lim} for i, n, c, e, lim in rows]


@router.get("/audit")
def audit_history(ctx: AuthContext = Depends(require_platform_admin), tenant_id: uuid.UUID | None = None, action: str | None = Query(None, max_length=64),
                  limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
    q = select(AuditLog, User.email, Tenant.name).outerjoin(User, User.id == AuditLog.user_id).outerjoin(Tenant, Tenant.id == AuditLog.tenant_id)
    if tenant_id:
        q = q.where(AuditLog.tenant_id == tenant_id)
    if action:
        q = q.where(AuditLog.action.ilike(f"{action}%"))
    rows = ctx.db.execute(q.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)).all()
    return [{"id": a.id, "action": a.action, "created_at": a.created_at, "user": email, "tenant": tname, "tenant_id": a.tenant_id, "entity_type": a.entity_type, "meta": a.meta} for a, email, tname in rows]


@router.get("/stats")
def platform_stats(ctx: AuthContext = Depends(require_platform_admin)):
    db = ctx.db
    by_status = dict(db.execute(select(QRCard.status, func.count()).group_by(QRCard.status)).all())
    events = dict(db.execute(select(ScanEvent.event_type, func.count()).where(ScanEvent.is_bot.is_(False)).group_by(ScanEvent.event_type)).all())
    subs = dict(db.execute(select(Subscription.status, func.count()).group_by(Subscription.status)).all())
    prices = {p.code: p.price_paise for p in db.scalars(select(BillingPlan))}
    mrr = sum(prices.get(s.plan, 0) for s in db.scalars(select(Subscription).where(Subscription.status == "active", Subscription.source == "razorpay")))
    since = utcnow() - timedelta(days=30)
    signups = dict(db.execute(select(func.date(Tenant.created_at), func.count()).where(Tenant.created_at >= since).group_by(func.date(Tenant.created_at))).all())
    revenue = dict(db.execute(select(Payment.kind, func.coalesce(func.sum(Payment.amount_paise), 0)).where(Payment.status == "captured").group_by(Payment.kind)).all())
    return {
        "tenants": db.scalar(select(func.count()).select_from(Tenant)), "suspended_tenants": db.scalar(select(func.count()).select_from(Tenant).where(Tenant.is_active.is_(False))),
        "open_support": db.scalar(select(func.count()).select_from(Tenant).where(Tenant.support_status.in_(["open", "waiting"]))),
        "locations": db.scalar(select(func.count()).select_from(Location)), "synced_reviews": db.scalar(select(func.count()).select_from(Review)),
        "cards_by_status": {k.value: v for k, v in by_status.items()}, "events": {k.value: v for k, v in events.items()},
        "subscriptions_by_status": subs, "mrr_paise": mrr,
        "revenue_paise": {"subscription": int(revenue.get("subscription", 0)), "card_order": int(revenue.get("card_order", 0))},
        "signups_30d": [{"date": (since + timedelta(days=i + 1)).date().isoformat(), "count": signups.get((since + timedelta(days=i + 1)).date(), 0)} for i in range(30)],
        "ai_generations_this_month": db.scalar(select(func.count()).select_from(AIGenerationLog).where(AIGenerationLog.created_at >= month_start())),
    }
