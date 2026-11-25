"""Platform-admin business provisioning: create a business and its locations without any shopkeeper account, edit them, record the offline agreement, manage access, and (optionally) invite the
shopkeeper to claim the business later. Every route requires a verified platform administrator (which is what switches on the database bypass for admin work); none is public. Tenant isolation for
everyone else is untouched. See services/provisioning.py for the rules."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select

from app.core.deps import AuthContext, require_platform_admin
from app.core.rate_limit import client_ip, hit
from app.models import Location, QRCard, Tenant
from app.schemas.provisioning import AdminBusinessIn, AgreementIn, BusinessPatchIn, ClaimIn, ClaimRevokeIn, DuplicateCheckIn, LocationAdminIn, LocationAdminPatch, ManagedAccessIn
from app.services import provisioning as prov
from app.services.audit import audit

router = APIRouter(prefix="/admin", tags=["platform-admin"])


def _tenant_or_404(ctx: AuthContext, tenant_id: uuid.UUID) -> Tenant:
    t = ctx.db.get(Tenant, tenant_id)
    if not t:
        raise HTTPException(status_code=404, detail="Business not found")
    return t


def _fail(exc: prov.ProvisionError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.detail())


def _loc_out(l: Location) -> dict:
    return {"id": l.id, "name": l.name, "address_line": l.address_line, "city": l.city, "phone": l.phone, "review_url": l.review_url, "is_active": l.is_active}


@router.post("/tenants/duplicate-check")
def duplicate_check(body: DuplicateCheckIn, ctx: AuthContext = Depends(require_platform_admin)):
    """Businesses that look like this one, with the reason. Read-only: nothing is created."""
    if not hit(f"admin-dupcheck:{ctx.user.id}", 120, 60):
        raise HTTPException(status_code=429, detail="Too many checks. Please wait a moment.")
    return {"matches": prov.find_duplicates(ctx.db, name=body.name, city=body.city, phone=body.phone, email=body.email, review_url=body.review_url)}


@router.post("/tenants", status_code=201)
def create_business(body: AdminBusinessIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Create a business, its first location and its managed access in one transaction. NO user, membership or password is created. If it looks like an existing business the answer is 409 with the
    matches; repeat the request with `duplicate_reason` to create it anyway (the reason is audited)."""
    if not hit(f"admin-create-business:{ctx.user.id}", 30, 600):
        raise HTTPException(status_code=429, detail="Too many businesses created in a short time. Try again in a few minutes.")
    data = body.model_dump()
    data["agreement"] = body.agreement.model_dump() if body.agreement else None
    try:
        t, loc = prov.create_business(ctx.db, admin=ctx.user, data=data, ip=client_ip(request))
    except prov.ProvisionError as exc:
        ctx.db.rollback()
        raise _fail(exc)
    ctx.db.commit()
    return {"id": t.id, "name": t.name, "origin": t.origin, "location": _loc_out(loc), "user_account_created": False}


@router.patch("/tenants/{tenant_id}")
def edit_business(tenant_id: uuid.UUID, body: BusinessPatchIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    t = _tenant_or_404(ctx, tenant_id)
    changes = body.model_dump(exclude_unset=True)
    if "services" in changes:  # the review page's keywords come from this list (services/review_suggestions.all_topics)
        rc = dict(t.review_context or {})
        rc["services"] = changes.pop("services") or []
        t.review_context = rc
        changes["services"] = None  # recorded in the audit entry by name only
    for k, v in changes.items():
        if k == "services" or (k == "name" and v is None):
            continue
        setattr(t, k, v)
    t.updated_by = ctx.user.id
    audit(ctx.db, action="admin.business_edit", tenant_id=t.id, user_id=ctx.user.id, entity_type="tenant", entity_id=t.id, ip=client_ip(request), meta={"fields": sorted(changes)})
    ctx.db.commit()
    return {"id": t.id, "name": t.name, "category": t.category, "contact_name": t.contact_name, "phone": t.phone, "email": t.email, "address": t.address, "website": t.website, **prov.review_keywords(t)}


@router.post("/tenants/{tenant_id}/locations", status_code=201)
def add_location(tenant_id: uuid.UUID, body: LocationAdminIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Another location for the business. An administrator is not held to the business's plan location limit here (an owner adding their own locations still is); the bypass is audited."""
    from app.services import entitlements as ent

    t = _tenant_or_404(ctx, tenant_id)
    e = ent.for_tenant(ctx.db, t.id)
    used = ent.locations_used(ctx.db, t.id)
    loc = Location(tenant_id=t.id, review_url_source="manual", **body.model_dump())
    ctx.db.add(loc)
    t.updated_by = ctx.user.id
    ctx.db.flush()
    audit(ctx.db, action="admin.location_create", tenant_id=t.id, user_id=ctx.user.id, entity_type="location", entity_id=loc.id, ip=client_ip(request),
          meta={"plan_limit_bypassed": bool(e.max_locations and used >= e.max_locations), "locations_before": used, "plan_limit": e.max_locations})
    ctx.db.commit()
    return _loc_out(loc)


@router.patch("/tenants/{tenant_id}/locations/{location_id}")
def edit_location(tenant_id: uuid.UUID, location_id: uuid.UUID, body: LocationAdminPatch, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    t = _tenant_or_404(ctx, tenant_id)
    loc = ctx.db.scalar(select(Location).where(Location.id == location_id, Location.tenant_id == t.id))
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    changes = body.model_dump(exclude_unset=True, exclude={"confirm"})
    if changes.get("is_active") is False and loc.is_active:
        live = ctx.db.scalar(select(func.count()).select_from(QRCard).where(QRCard.location_id == loc.id, QRCard.status.in_(prov.LIVE_CARD_STATUSES))) or 0
        if live and not body.confirm:
            raise HTTPException(status_code=409, detail={"code": "confirmation_required", "message": f"{live} live card(s) point at this location. Deactivating it makes every scan or tap show 'no longer active'.",
                                                         "current": {"location": loc.name, "live_cards": live}, "new": {"location": "deactivated"}})
    for k, v in changes.items():
        setattr(loc, k, v)
    if "review_url" in changes:
        loc.review_url_source = "manual"
    t.updated_by = ctx.user.id
    audit(ctx.db, action="admin.location_edit", tenant_id=t.id, user_id=ctx.user.id, entity_type="location", entity_id=loc.id, ip=client_ip(request), meta={"fields": sorted(changes)})
    ctx.db.commit()
    return _loc_out(loc)


@router.post("/tenants/{tenant_id}/agreement", status_code=201)
def add_agreement(tenant_id: uuid.UUID, body: AgreementIn, ctx: AuthContext = Depends(require_platform_admin)):
    """Record that YOU took this business through the terms offline. It is stored as an administrator's statement, never as the shopkeeper's own acceptance or an age confirmation."""
    t = _tenant_or_404(ctx, tenant_id)
    try:
        row = prov.record_agreement(ctx.db, t, by=ctx.user.id, method=body.method, note=body.note)
    except prov.ProvisionError as exc:
        ctx.db.rollback()
        raise _fail(exc)
    ctx.db.commit()
    return {"id": row.id, "recorded_at": row.recorded_at, "terms_version": row.terms_version, "method": row.method, "note": row.note, "statement": row.statement}


@router.post("/tenants/{tenant_id}/managed-access")
def managed_access(tenant_id: uuid.UUID, body: ManagedAccessIn, ctx: AuthContext = Depends(require_platform_admin)):
    """Revoke or restore the Launch access of an admin-managed business. Revoking stops the AI features; cards, scans and the plain review page keep working."""
    t = _tenant_or_404(ctx, tenant_id)
    try:
        sub = prov.set_managed_access(ctx.db, t, revoke=body.action == "revoke", by=ctx.user.id, note=body.note)
    except prov.ProvisionError as exc:
        ctx.db.rollback()
        raise _fail(exc)
    ctx.db.commit()
    return {"state": prov.managed_state(sub), "status": sub.status}


@router.post("/tenants/{tenant_id}/claim", status_code=201)
def create_claim(tenant_id: uuid.UUID, body: ClaimIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """OPTIONAL: invite the shopkeeper to take ownership of this business. Off unless CLAIM_INVITATIONS_ENABLED. Nothing about cards depends on it."""
    if not hit(f"admin-claim:{ctx.user.id}", 30, 600):
        raise HTTPException(status_code=429, detail="Too many invitations. Try again in a few minutes.")
    t = _tenant_or_404(ctx, tenant_id)
    try:
        out = prov.create_claim_invitation(ctx.db, t, admin=ctx.user, email=body.email, delivery=body.delivery, ip=client_ip(request))
    except prov.ProvisionError as exc:
        ctx.db.rollback()
        raise _fail(exc)
    ctx.db.commit()
    return out


@router.post("/tenants/{tenant_id}/claim/{invitation_id}/revoke")
def revoke_claim(tenant_id: uuid.UUID, invitation_id: uuid.UUID, request: Request, body: ClaimRevokeIn | None = None, ctx: AuthContext = Depends(require_platform_admin)):
    """Revoke a claim invitation. The sign-up allowlist entry it created is removed ONLY if `remove_from_allowlist` is set AND nothing else needs the address (see
    services/provisioning.allowlist_removal_check); the answer says what happened and why. The invitation and audit history are kept. Safe to repeat."""
    t = _tenant_or_404(ctx, tenant_id)
    try:
        out = prov.revoke_claim_invitation(ctx.db, t, invitation_id, admin=ctx.user, ip=client_ip(request), remove_from_allowlist=bool(body and body.remove_from_allowlist))
    except prov.ProvisionError as exc:
        ctx.db.rollback()
        raise _fail(exc)
    ctx.db.commit()
    return out


@router.get("/managed-usage")
def managed_usage(ctx: AuthContext = Depends(require_platform_admin)):
    """This month's AI review-writing and reply use, and estimated AI cost, across the businesses FlowQR staff manage. Read-only; figures come from recorded usage and the configured prices."""
    return prov.managed_usage(ctx.db)
