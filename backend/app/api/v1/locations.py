import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select

from app.core.deps import TenantContext, get_tenant_context, require_role
from app.core.rate_limit import client_ip
from app.models import Location, Role, Subscription
from app.schemas.locations import LocationIn, LocationOut, LocationUpdate
from app.services.audit import audit

router = APIRouter(prefix="/locations", tags=["locations"])


def get_location_or_404(ctx: TenantContext, location_id: uuid.UUID) -> Location:
    loc = ctx.db.scalar(select(Location).where(Location.id == location_id, Location.tenant_id == ctx.tenant_id))
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    return loc


@router.get("", response_model=list[LocationOut])
def list_locations(ctx: TenantContext = Depends(get_tenant_context)):
    return ctx.db.scalars(select(Location).where(Location.tenant_id == ctx.tenant_id).order_by(Location.created_at)).all()


@router.post("", response_model=LocationOut, status_code=201)
def create_location(body: LocationIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    sub = ctx.db.scalar(select(Subscription).where(Subscription.tenant_id == ctx.tenant_id))
    count = ctx.db.scalar(select(func.count()).select_from(Location).where(Location.tenant_id == ctx.tenant_id))
    if sub and count >= sub.max_locations:
        raise HTTPException(status_code=402, detail=f"Your plan allows up to {sub.max_locations} locations")
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
def update_location(location_id: uuid.UUID, body: LocationUpdate, request: Request,
                    ctx: TenantContext = Depends(require_role(Role.admin))):
    loc = get_location_or_404(ctx, location_id)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(loc, k, v)
    if "review_url" in data:
        loc.review_url_source = "manual"
    audit(ctx.db, action="location.update", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="location",
          entity_id=loc.id, meta={"fields": sorted(data)}, ip=client_ip(request))
    ctx.db.commit()
    return loc


@router.delete("/{location_id}", status_code=204)
def delete_location(location_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.owner))):
    loc = get_location_or_404(ctx, location_id)
    loc.is_active = False  # soft delete: cards, scan history and reviews keep their references
    audit(ctx.db, action="location.deactivate", tenant_id=ctx.tenant_id, user_id=ctx.user.id,
          entity_type="location", entity_id=loc.id, ip=client_ip(request))
    ctx.db.commit()
