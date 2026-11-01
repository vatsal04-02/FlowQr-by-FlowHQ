"""Tenant-facing card management (admin+ may re-point/label/deactivate cards assigned to them)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select

from app.core.deps import TenantContext, get_tenant_context, require_role
from app.core.rate_limit import client_ip
from app.models import CardStatus, Location, QRCard, Role, Tenant
from app.schemas.cards import CardOut, CardPatchIn
from app.services import cards as svc
from app.services.audit import audit
from app.services.qr import card_url, qr_png, qr_svg

router = APIRouter(prefix="/cards", tags=["cards"])


def card_out(card: QRCard, *, stats=None, tenant_name=None, location_name=None, include_token=True) -> CardOut:
    return CardOut(
        id=card.id, card_code=card.card_code, status=card.status, batch_id=card.batch_id, tenant_id=card.tenant_id,
        location_id=card.location_id, label=card.label, assigned_at=card.assigned_at, url=card_url(card.public_token),
        public_token=card.public_token if include_token else None,
        tenant_name=tenant_name, location_name=location_name, stats=stats or {},
    )


def get_own_card(ctx: TenantContext, card_id: uuid.UUID) -> QRCard:
    card = ctx.db.scalar(select(QRCard).where(QRCard.id == card_id, QRCard.tenant_id == ctx.tenant_id))
    if not card:
        raise HTTPException(status_code=404, detail="Card not found")
    return card


@router.get("", response_model=list[CardOut])
def list_cards(ctx: TenantContext = Depends(get_tenant_context)):
    cards = ctx.db.scalars(select(QRCard).where(QRCard.tenant_id == ctx.tenant_id).order_by(QRCard.card_code)).all()
    locs = {l.id: l.name for l in ctx.db.scalars(select(Location).where(Location.tenant_id == ctx.tenant_id))}
    counts = svc.card_scan_counts(ctx.db, [c.id for c in cards])
    return [card_out(c, stats=counts.get(c.id), location_name=locs.get(c.location_id), tenant_name=ctx.tenant.name) for c in cards]


@router.patch("/{card_id}", response_model=CardOut)
def update_card(card_id: uuid.UUID, body: CardPatchIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    card = get_own_card(ctx, card_id)
    data = body.model_dump(exclude_unset=True)
    if "label" in data:
        card.label = data["label"]
    if data.get("location_id") and data["location_id"] != card.location_id:
        loc = ctx.db.scalar(select(Location).where(Location.id == data["location_id"], Location.tenant_id == ctx.tenant_id))
        if not loc:
            raise HTTPException(status_code=404, detail="Location not found")
        svc.assign_card(ctx.db, card, tenant=ctx.tenant, location=loc, by=ctx.user.id)
        audit(ctx.db, action="card.repoint", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="card",
              entity_id=card.id, meta={"location_id": str(loc.id)}, ip=client_ip(request))
    ctx.db.commit()
    return card_out(card, tenant_name=ctx.tenant.name)


@router.post("/{card_id}/deactivate", response_model=CardOut)
def deactivate(card_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    card = get_own_card(ctx, card_id)
    card.status = CardStatus.deactivated
    audit(ctx.db, action="card.deactivate", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="card",
          entity_id=card.id, ip=client_ip(request))
    ctx.db.commit()
    return card_out(card)


@router.post("/{card_id}/report-lost", response_model=CardOut)
def report_lost(card_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    card = get_own_card(ctx, card_id)
    card.status = CardStatus.lost
    audit(ctx.db, action="card.lost", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="card",
          entity_id=card.id, ip=client_ip(request))
    ctx.db.commit()
    return card_out(card)


@router.post("/{card_id}/activate", response_model=CardOut)
def activate(card_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    card = get_own_card(ctx, card_id)
    if card.status == CardStatus.lost:
        raise HTTPException(status_code=400, detail="Contact FlowQR support to re-enable a card reported lost")
    card.status = CardStatus.active
    audit(ctx.db, action="card.activate", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="card",
          entity_id=card.id, ip=client_ip(request))
    ctx.db.commit()
    return card_out(card)


@router.get("/{card_id}/qr.{fmt}")
def card_qr(card_id: uuid.UUID, fmt: str, ctx: TenantContext = Depends(require_role(Role.admin))):
    card = get_own_card(ctx, card_id)
    url = card_url(card.public_token)
    if fmt == "png":
        return Response(qr_png(url), media_type="image/png",
                        headers={"Content-Disposition": f'attachment; filename="{card.card_code}.png"'})
    if fmt == "svg":
        return Response(qr_svg(url), media_type="image/svg+xml",
                        headers={"Content-Disposition": f'attachment; filename="{card.card_code}.svg"'})
    raise HTTPException(status_code=404, detail="Unsupported format")
