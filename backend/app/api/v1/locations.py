import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select

from app.core.deps import TenantContext, get_tenant_context, require_role
from app.core.rate_limit import client_ip
from app.models import CardStatus, Location, QRCard, ReviewCampaign, Role, Subscription
from app.schemas.locations import LocationIn, LocationOut, LocationUpdate
from app.services import entitlements as ent
from app.services.audit import audit

router = APIRouter(prefix="/locations", tags=["locations"])


def get_location_or_404(ctx: TenantContext, location_id: uuid.UUID) -> Location:
    loc = ctx.db.scalar(select(Location).where(Location.id == location_id, Location.tenant_id == ctx.tenant_id))
    if not loc or not ctx.can_access_location(loc.id):
        raise HTTPException(status_code=404, detail="Location not found")
    return loc


def live_codes(ctx: TenantContext, loc: Location) -> dict:
    """Printed codes that currently work and lead to this location."""
    cards = ctx.db.scalar(select(func.count()).select_from(QRCard).where(
        QRCard.tenant_id == ctx.tenant_id, QRCard.location_id == loc.id, QRCard.status.in_([CardStatus.assigned, CardStatus.active]))) or 0
    campaigns = ctx.db.scalar(select(func.count()).select_from(ReviewCampaign).where(
        ReviewCampaign.tenant_id == ctx.tenant_id, ReviewCampaign.location_id == loc.id, ReviewCampaign.status == "active")) or 0
    return {"cards": cards, "campaigns": campaigns}


def confirm_codes_stop(ctx: TenantContext, loc: Location, confirmed: bool) -> dict:
    """Deactivating a location makes every code that leads to it show "no longer active". That is never done implicitly:
    if any live code points here the caller gets a 409 naming how many, and must repeat the request with confirm=true."""
    codes = live_codes(ctx, loc)
    if (codes["cards"] or codes["campaigns"]) and not confirmed:
        raise HTTPException(status_code=409, detail={
            "code": "codes_would_stop", **codes,
            "message": f"{codes['cards']} card(s) and {codes['campaigns']} QR campaign(s) lead to this location. If you deactivate it, their printed "
                       "codes will show a 'no longer active' page until you reactivate it or move them to another location."})
    return codes


@router.get("", response_model=list[LocationOut])
def list_locations(ctx: TenantContext = Depends(get_tenant_context)):
    return ctx.db.scalars(select(Location).where(Location.tenant_id == ctx.tenant_id, ctx.scope(Location.id)).order_by(Location.created_at)).all()


@router.post("", response_model=LocationOut, status_code=201)
def create_location(body: LocationIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    e = ent.require_active(ctx.db, ctx.tenant_id)
    if ent.locations_used(ctx.db, ctx.tenant_id) >= e.max_locations:
        raise HTTPException(status_code=402, detail={"code": "plan_limit", "message": f"Your plan allows up to {e.max_locations} locations. Upgrade to add more."})
    loc = Location(tenant_id=ctx.tenant_id, **body.model_dump())
    ctx.db.add(loc)
    ctx.db.flush()
    audit(ctx.db, action="location.create", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="location",
          entity_id=loc.id, ip=client_ip(request))
    ctx.db.commit()
    return loc


@router.get("/{location_id}", response_model=LocationOut)
def get_location(location_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    return get_location_or_404(ctx, location_id)


@router.patch("/{location_id}", response_model=LocationOut)
def update_location(location_id: uuid.UUID, body: LocationUpdate, request: Request, confirm: bool = False,
                    ctx: TenantContext = Depends(require_role(Role.admin))):
    loc = get_location_or_404(ctx, location_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("is_active") is False and loc.is_active:
        data_codes = confirm_codes_stop(ctx, loc, confirm)
        audit(ctx.db, action="location.deactivate", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="location",
              entity_id=loc.id, meta={"codes_stopped": data_codes}, ip=client_ip(request))
    for k, v in data.items():
        setattr(loc, k, v)
    if "review_url" in data:
        loc.review_url_source = "manual"
    audit(ctx.db, action="location.update", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="location",
          entity_id=loc.id, meta={"fields": sorted(data)}, ip=client_ip(request))
    ctx.db.commit()
    return loc


@router.delete("/{location_id}", status_code=204)
def delete_location(location_id: uuid.UUID, request: Request, confirm: bool = False, ctx: TenantContext = Depends(require_role(Role.owner))):
    loc = get_location_or_404(ctx, location_id)
    codes = confirm_codes_stop(ctx, loc, confirm) if loc.is_active else {}
    loc.is_active = False  # soft delete: cards, scan history and reviews keep their references; no code or link is changed
    audit(ctx.db, action="location.deactivate", tenant_id=ctx.tenant_id, user_id=ctx.user.id,
          entity_type="location", entity_id=loc.id, meta={"codes_stopped": codes}, ip=client_ip(request))
    ctx.db.commit()
