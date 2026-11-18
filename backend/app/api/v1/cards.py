"""Tenant-facing card management.

A business sees only cards that belong to it (database row-level security plus the checks here). Stock that belongs to nobody
is invisible to tenants, so a business cannot claim, find or reassign a card FlowHQ has not given it: FlowHQ reserves or
assigns the card to the business first (admin API), and then an owner/admin of that business gives it a location and a campaign.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select

from app.core.deps import TenantContext, get_tenant_context, require_role
from app.core.rate_limit import client_ip, hit
from app.models import CardBatch, CardStatus, Location, QRCard, ReviewCampaign, Role
from app.schemas.cards import CardOut, CardPatchIn, ConfirmIn, LookupIn, TenantAssignIn
from app.services import cards as svc
from app.services.audit import audit
from app.services.qr import card_nfc_url, card_qr_url

router = APIRouter(prefix="/cards", tags=["cards"])


def card_out(card: QRCard, *, stats=None, tenant_name=None, location_name=None, include_token=True, last_scan_at=None,
             campaign_name=None, batch_name=None) -> CardOut:
    return CardOut(
        id=card.id, card_code=card.card_code, status=card.status, batch_id=card.batch_id, tenant_id=card.tenant_id,
        location_id=card.location_id, label=card.label, assigned_at=card.assigned_at, url=card_qr_url(card),
        nfc_url=card_nfc_url(card.public_token), campaign_id=card.campaign_id, campaign_name=campaign_name, batch_name=batch_name,
        public_token=card.public_token if include_token else None,
        tenant_name=tenant_name, location_name=location_name, stats=stats or {}, last_scan_at=last_scan_at,
        destination_url=card.destination_url, nfc_programmed_at=card.nfc_programmed_at,
    )


def names_for(db, cards: list[QRCard]) -> tuple[dict, dict, dict]:
    """(location names, campaign names, batch names) for these cards, in three queries."""
    loc_ids = [c.location_id for c in cards if c.location_id]
    camp_ids = [c.campaign_id for c in cards if c.campaign_id]
    batch_ids = [c.batch_id for c in cards if c.batch_id]
    locs = {l.id: l.name for l in db.scalars(select(Location).where(Location.id.in_(loc_ids)))} if loc_ids else {}
    camps = {c.id: c.name for c in db.scalars(select(ReviewCampaign).where(ReviewCampaign.id.in_(camp_ids)))} if camp_ids else {}
    batches = {b.id: b.name for b in db.scalars(select(CardBatch).where(CardBatch.id.in_(batch_ids)))} if batch_ids else {}
    return locs, camps, batches


def get_own_card(ctx: TenantContext, card_id: uuid.UUID) -> QRCard:
    """This business's card, or 404. A card with no location yet (reserved) is visible only to members who may see every location."""
    card = ctx.db.scalar(select(QRCard).where(QRCard.id == card_id, QRCard.tenant_id == ctx.tenant_id))
    if not card or not ctx.can_access_location(card.location_id):
        raise HTTPException(status_code=404, detail="Card not found")
    return card


def _full(ctx: TenantContext, card: QRCard) -> CardOut:
    locs, camps, batches = names_for(ctx.db, [card])
    return card_out(card, tenant_name=ctx.tenant.name, location_name=locs.get(card.location_id), campaign_name=camps.get(card.campaign_id),
                    batch_name=batches.get(card.batch_id), stats=svc.card_scan_counts(ctx.db, [card.id]).get(card.id))


def _own_location(ctx: TenantContext, location_id: uuid.UUID) -> Location:
    loc = ctx.db.scalar(select(Location).where(Location.id == location_id, Location.tenant_id == ctx.tenant_id))
    if not loc or not ctx.can_access_location(loc.id):
        raise HTTPException(status_code=404, detail="Location not found")
    return loc


@router.get("", response_model=list[CardOut])
def list_cards(ctx: TenantContext = Depends(get_tenant_context)):
    # Reserved cards have no location yet: only members who may see every location see them (a restricted teammate sees cards at their locations).
    cards = ctx.db.scalars(select(QRCard).where(QRCard.tenant_id == ctx.tenant_id, ctx.scope(QRCard.location_id)).order_by(QRCard.card_code)).all()
    locs, camps, batches = names_for(ctx.db, list(cards))
    counts = svc.card_scan_counts(ctx.db, [c.id for c in cards])
    last = svc.card_last_scans(ctx.db, [c.id for c in cards])
    return [card_out(c, stats=counts.get(c.id), location_name=locs.get(c.location_id), campaign_name=camps.get(c.campaign_id),
                     batch_name=batches.get(c.batch_id), tenant_name=ctx.tenant.name, last_scan_at=last.get(c.id)) for c in cards]


@router.post("/lookup", response_model=CardOut)
def lookup(body: LookupIn, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Identify a card the user just scanned or typed. Only this business's own cards are found: a card that belongs to nobody, or to
    another business, answers exactly like a card that does not exist."""
    if not hit(f"card-lookup:{ctx.user.id}", 60, 60):
        raise HTTPException(status_code=429, detail="Too many lookups. Please wait a moment.")
    card = svc.find_by_scan(ctx.db, body.scan)
    if not card or card.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="This card is not available to your business. Cards are given to a business by FlowHQ first.")
    return _full(ctx, card)


@router.post("/{card_id}/assign", response_model=CardOut)
def assign(card_id: uuid.UUID, body: TenantAssignIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Give one of THIS business's cards (reserved for it, or already in use) a location and, optionally, a review campaign."""
    card = get_own_card(ctx, card_id)
    if card.status not in svc.OWNED_STATUSES:
        raise HTTPException(status_code=409, detail="This card cannot be assigned from its current state.")
    loc = _own_location(ctx, body.location_id)
    campaign = svc.check_campaign(ctx.db, body.campaign_id, ctx.tenant, loc)
    svc.assign_card(ctx.db, card, tenant=ctx.tenant, location=loc, by=ctx.user.id, campaign=campaign, confirm=body.confirm, activate=body.activate)
    if body.label is not None:
        card.label = body.label
    audit(ctx.db, action="card.assign", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="card", entity_id=card.id,
          meta={"location_id": str(loc.id), "campaign_id": str(campaign.id) if campaign else None}, ip=client_ip(request))
    ctx.db.commit()
    return _full(ctx, card)


@router.patch("/{card_id}", response_model=CardOut)
def update_card(card_id: uuid.UUID, body: CardPatchIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Label a card, or change where it points. Changing the destination of a card in use needs `confirm`, and applies at once to
    the printed QR and the NFC tag: neither is rewritten."""
    card = get_own_card(ctx, card_id)
    data = body.model_dump(exclude_unset=True)
    if "label" in data:
        card.label = data["label"]
    wants_location = data.get("location_id") and data["location_id"] != card.location_id
    wants_campaign = data.get("clear_campaign") or ("campaign_id" in data and data["campaign_id"] != card.campaign_id)
    if wants_location or wants_campaign:
        loc = _own_location(ctx, data["location_id"]) if wants_location else ctx.db.get(Location, card.location_id)
        campaign_id = None if data.get("clear_campaign") else (data["campaign_id"] if "campaign_id" in data else (None if wants_location else card.campaign_id))
        campaign = svc.check_campaign(ctx.db, campaign_id, ctx.tenant, loc)
        svc.assign_card(ctx.db, card, tenant=ctx.tenant, location=loc, by=ctx.user.id, campaign=campaign, confirm=body.confirm)
        audit(ctx.db, action="card.repoint", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="card",
              entity_id=card.id, meta={"location_id": str(loc.id), "campaign_id": str(campaign.id) if campaign else None}, ip=client_ip(request))
    ctx.db.commit()
    return _full(ctx, card)


@router.post("/{card_id}/retire", response_model=CardOut)
def retire(card_id: uuid.UUID, body: ConfirmIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Permanently take a card out of use. Requires explicit confirmation. History and scan counts are kept."""
    card = get_own_card(ctx, card_id)
    svc.retire_card(ctx.db, card, confirm=body.confirm)
    audit(ctx.db, action="card.retire", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="card", entity_id=card.id, ip=client_ip(request))
    ctx.db.commit()
    return _full(ctx, card)


@router.post("/{card_id}/deactivate", response_model=CardOut)
def deactivate(card_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    card = get_own_card(ctx, card_id)
    if card.status == CardStatus.retired:
        raise HTTPException(status_code=409, detail="This card has been retired.")
    card.status = CardStatus.deactivated
    audit(ctx.db, action="card.deactivate", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="card",
          entity_id=card.id, ip=client_ip(request))
    ctx.db.commit()
    return card_out(card)


@router.post("/{card_id}/pause", response_model=CardOut)
def pause(card_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Temporarily switch a card off. The printed code is unchanged and works again as soon as the card is resumed."""
    card = get_own_card(ctx, card_id)
    if card.status not in svc.LIVE_STATUSES:
        raise HTTPException(status_code=409, detail="Only a live card can be paused")
    card.status = CardStatus.paused
    audit(ctx.db, action="card.pause", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="card",
          entity_id=card.id, ip=client_ip(request))
    ctx.db.commit()
    return card_out(card)


@router.post("/{card_id}/report-lost", response_model=CardOut)
def report_lost(card_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    card = get_own_card(ctx, card_id)
    if card.status == CardStatus.retired:
        raise HTTPException(status_code=409, detail="This card has been retired.")
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
    if card.status in (CardStatus.retired, CardStatus.archived, CardStatus.reserved, CardStatus.generated, CardStatus.unassigned) or not card.location_id:
        raise HTTPException(status_code=409, detail="This card cannot be switched on from its current state.")
    card.status = CardStatus.active
    audit(ctx.db, action="card.activate", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="card",
          entity_id=card.id, ip=client_ip(request))
    ctx.db.commit()
    return card_out(card)


@router.get("/{card_id}/qr.{fmt}")
def card_qr(card_id: uuid.UUID, fmt: str, size: int | None = Query(None, ge=256, le=4096), ctx: TenantContext = Depends(require_role(Role.admin))):
    """The card's code as PNG, SVG or PDF in the business's QR style. Always encodes the card's permanent URL."""
    from app.api.v1.qr import qr_response, tenant_style

    card = get_own_card(ctx, card_id)
    style, logo = tenant_style(ctx.db, ctx.tenant_id)
    return qr_response(card_qr_url(card), fmt, style, logo, card.card_code, size_px=size)


@router.get("/{card_id}/poster.{fmt}")
def card_poster(card_id: uuid.UUID, fmt: str, scale: int = Query(1, ge=1, le=3), size: str = Query("ref"),
                ctx: TenantContext = Depends(require_role(Role.admin))):
    """The approved FlowQR review poster with this card's permanent code in it. PNG, SVG or print-ready PDF."""
    from app.api.v1.qr import poster_response

    card = get_own_card(ctx, card_id)
    return poster_response(card_qr_url(card), fmt, card.card_code, scale=scale, size=size, serial=card.card_code)
