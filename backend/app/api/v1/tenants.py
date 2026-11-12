import re
import secrets
import uuid as _uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.db import set_rls_context
from app.core.deps import AuthContext, ensure_verified, TenantContext, get_auth_context, get_tenant_context, require_role
from app.core.rate_limit import client_ip
from app.core.security import hash_token, new_token
from app.models import Invitation, Location, Membership, MembershipLocation, Role, Subscription, Tenant, User
from app.models.base import utcnow
from app.schemas.auth import (
    InvitationAcceptIn, InvitationOut, InviteIn, MemberOut, RoleUpdateIn, StaffLocationsIn, TenantCreateIn, TenantOut, TenantUpdateIn,
)
from app.services import billing as billing_svc
from app.services import entitlements as ent
from app.services.audit import audit
from app.services.mailer import send_email

router = APIRouter(tags=["tenant"])


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:50] or "business"
    return f"{base}-{secrets.token_hex(3)}"


@router.post("/tenants", response_model=TenantOut, status_code=201)
def create_tenant(body: TenantCreateIn, request: Request, ctx: AuthContext = Depends(get_auth_context)):
    """Onboarding step 2. The creating user becomes Owner. Everything happens in one transaction."""
    db = ctx.db
    set_rls_context(db, bypass=True)
    owned = db.scalar(
        select(func.count()).select_from(Membership).where(Membership.user_id == ctx.user.id, Membership.role == Role.owner)
    )
    if owned >= 5:
        raise HTTPException(status_code=400, detail="Business limit reached for this account")
    tenant = Tenant(slug=_slugify(body.name), **body.model_dump())
    db.add(tenant)
    db.flush()
    db.add(Membership(tenant_id=tenant.id, user_id=ctx.user.id, role=Role.owner))
    billing_svc.start_trial(db, tenant.id)
    ctx.session.active_tenant_id = tenant.id
    audit(db, action="tenant.create", tenant_id=tenant.id, user_id=ctx.user.id, entity_type="tenant",
          entity_id=tenant.id, ip=client_ip(request))
    db.commit()
    set_rls_context(db)
    return tenant


@router.get("/tenant", response_model=TenantOut)
def get_tenant(ctx: TenantContext = Depends(get_tenant_context)):
    return ctx.tenant


@router.patch("/tenant", response_model=TenantOut)
def update_tenant(body: TenantUpdateIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(ctx.tenant, k, v)
    audit(ctx.db, action="tenant.update", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="tenant",
          entity_id=ctx.tenant_id, meta={"fields": sorted(data)}, ip=client_ip(request))
    ctx.db.commit()
    return ctx.tenant


@router.post("/tenant/complete-onboarding", response_model=TenantOut)
def complete_onboarding(ctx: TenantContext = Depends(require_role(Role.admin))):
    count = ctx.db.scalar(select(func.count()).select_from(Location).where(Location.tenant_id == ctx.tenant_id))
    if not count:
        raise HTTPException(status_code=400, detail="Add at least one location first")
    ctx.tenant.onboarding_completed = True
    ctx.db.commit()
    return ctx.tenant


# ---------------- Staff ----------------

@router.get("/staff")
def list_staff(ctx: TenantContext = Depends(get_tenant_context)):
    members = ctx.db.execute(
        select(Membership, User).join(User, User.id == Membership.user_id).where(Membership.tenant_id == ctx.tenant_id)
    ).all()
    invites = ctx.db.scalars(
        select(Invitation).where(
            Invitation.tenant_id == ctx.tenant_id, Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None),
            Invitation.expires_at > utcnow(),
        )
    ).all()
    assigned: dict = {}
    for mid, lid in ctx.db.execute(select(MembershipLocation.membership_id, MembershipLocation.location_id).where(MembershipLocation.tenant_id == ctx.tenant_id)):
        assigned.setdefault(mid, []).append(lid)

    def scope_of(m: Membership) -> dict:
        limited = m.role == Role.staff and not m.all_locations
        return {"all_locations": not limited, "location_ids": assigned.get(m.id, []) if limited else []}
    return {
        "members": [MemberOut(user_id=u.id, email=u.email, full_name=u.full_name, role=m.role, **scope_of(m)) for m, u in members],
        "invitations": [InvitationOut.model_validate(i) for i in invites],
    }


@router.post("/staff/invitations", response_model=InvitationOut, status_code=201)
def invite_staff(body: InviteIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    if body.role == Role.owner or (body.role == Role.admin and ctx.role != Role.owner):
        raise HTTPException(status_code=403, detail="Only an owner can invite admins; owners cannot be invited")
    ensure_verified(ctx.user)
    e = ent.require_active(ctx.db, ctx.tenant_id)
    if ent.seats_used(ctx.db, ctx.tenant_id) >= e.max_staff:
        raise HTTPException(status_code=402, detail={"code": "plan_limit", "message": f"Your plan allows up to {e.max_staff} team members."})
    email = body.email.lower()
    token = new_token()
    location_ids = None
    if body.location_ids is not None:
        if body.role != Role.staff:
            raise HTTPException(status_code=422, detail="Only staff can be limited to specific locations")
        location_ids = [str(i) for i in _own_location_ids(ctx, body.location_ids)]
    inv = Invitation(
        tenant_id=ctx.tenant_id, email=email, role=body.role, token_hash=hash_token(token), invited_by=ctx.user.id, location_ids=location_ids,
        expires_at=utcnow() + timedelta(hours=settings.invitation_ttl_hours),
    )
    ctx.db.add(inv)
    audit(ctx.db, action="staff.invite", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="invitation",
          entity_id=inv.id, meta={"email": email, "role": body.role.value, "locations": "all" if location_ids is None else len(location_ids)}, ip=client_ip(request))
    ctx.db.commit()
    sent = send_email(email, f"You're invited to {ctx.tenant.name} on FlowQR",
                      f"Accept the invitation:\n{settings.frontend_url}/accept-invite?token={token}")
    out = InvitationOut.model_validate(inv)
    out.email_sent = sent  # never claim delivery we can't confirm
    return out


@router.delete("/staff/invitations/{invitation_id}", status_code=204)
def revoke_invitation(invitation_id: str, ctx: TenantContext = Depends(require_role(Role.admin))):
    try:
        iid = _uuid.UUID(invitation_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found")
    inv = ctx.db.scalar(select(Invitation).where(Invitation.id == iid, Invitation.tenant_id == ctx.tenant_id))
    if not inv:
        raise HTTPException(status_code=404, detail="Not found")
    inv.revoked_at = utcnow()
    ctx.db.commit()


@router.post("/invitations/accept", response_model=TenantOut)
def accept_invitation(body: InvitationAcceptIn, request: Request, ctx: AuthContext = Depends(get_auth_context)):
    db = ctx.db
    set_rls_context(db, bypass=True)
    inv = db.scalar(select(Invitation).where(Invitation.token_hash == hash_token(body.token)))
    if not inv or inv.accepted_at or inv.revoked_at or inv.expires_at < utcnow() or inv.email != ctx.user.email:
        raise HTTPException(status_code=400, detail="This invitation is invalid, expired, or for a different email")
    if not db.scalar(select(Membership).where(Membership.tenant_id == inv.tenant_id, Membership.user_id == ctx.user.id)):
        limited = inv.role == Role.staff and inv.location_ids is not None
        m = Membership(tenant_id=inv.tenant_id, user_id=ctx.user.id, role=inv.role, all_locations=not limited)
        db.add(m)
        db.flush()
        if limited:  # only locations that still exist in this tenant
            wanted = [_uuid.UUID(i) for i in inv.location_ids]
            for lid in db.scalars(select(Location.id).where(Location.tenant_id == inv.tenant_id, Location.id.in_(wanted))) if wanted else []:
                db.add(MembershipLocation(tenant_id=inv.tenant_id, membership_id=m.id, location_id=lid))
    inv.accepted_at = utcnow()
    ctx.session.active_tenant_id = inv.tenant_id
    audit(db, action="staff.accept", tenant_id=inv.tenant_id, user_id=ctx.user.id, entity_type="invitation",
          entity_id=inv.id, ip=client_ip(request))
    db.commit()
    tenant = db.get(Tenant, inv.tenant_id)
    set_rls_context(db)
    return tenant


def _own_location_ids(ctx: TenantContext, ids: list) -> list:
    """Validate that every id is a location of THIS tenant (a foreign or unknown id is a 404, never silently dropped)."""
    wanted = list(dict.fromkeys(ids))
    found = set(ctx.db.scalars(select(Location.id).where(Location.tenant_id == ctx.tenant_id, Location.id.in_(wanted)))) if wanted else set()
    if len(found) != len(wanted):
        raise HTTPException(status_code=404, detail="Location not found")
    return wanted


def _get_member(ctx: TenantContext, user_id: str) -> Membership:
    try:
        uid = _uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Not found")
    m = ctx.db.scalar(select(Membership).where(Membership.tenant_id == ctx.tenant_id, Membership.user_id == uid))
    if not m:
        raise HTTPException(status_code=404, detail="Not found")
    return m


def _owner_count(ctx: TenantContext) -> int:
    return ctx.db.scalar(
        select(func.count()).select_from(Membership).where(Membership.tenant_id == ctx.tenant_id, Membership.role == Role.owner)
    )


@router.patch("/staff/{user_id}", status_code=204)
def change_role(user_id: str, body: RoleUpdateIn, request: Request, ctx: TenantContext = Depends(require_role(Role.owner))):
    m = _get_member(ctx, user_id)
    if m.role == Role.owner and body.role != Role.owner and _owner_count(ctx) <= 1:
        raise HTTPException(status_code=400, detail="A business must have at least one owner")
    m.role = body.role
    if body.role != Role.staff:  # owners/admins always have every location: drop any old restriction so a later demotion can't revive it
        m.all_locations = True
        ctx.db.execute(delete(MembershipLocation).where(MembershipLocation.membership_id == m.id))
    audit(ctx.db, action="staff.role_change", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="membership",
          entity_id=m.id, meta={"role": body.role.value}, ip=client_ip(request))
    ctx.db.commit()


@router.delete("/staff/{user_id}", status_code=204)
def remove_member(user_id: str, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    m = _get_member(ctx, user_id)
    if m.role == Role.owner and (ctx.role != Role.owner or _owner_count(ctx) <= 1):
        raise HTTPException(status_code=400, detail="The last owner cannot be removed")
    if m.role == Role.admin and ctx.role != Role.owner:
        raise HTTPException(status_code=403, detail="Only an owner can remove admins")
    ctx.db.delete(m)
    audit(ctx.db, action="staff.remove", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="membership",
          entity_id=m.id, ip=client_ip(request))
    ctx.db.commit()


@router.put("/staff/{user_id}/locations", status_code=204)
def set_member_locations(user_id: str, body: StaffLocationsIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Limit a staff member to specific locations (or give them all). Owners and admins cannot be limited."""
    m = _get_member(ctx, user_id)
    if m.role != Role.staff:
        raise HTTPException(status_code=400, detail="Owners and admins always have access to every location")
    ids = [] if body.all_locations else _own_location_ids(ctx, body.location_ids)
    m.all_locations = body.all_locations
    ctx.db.execute(delete(MembershipLocation).where(MembershipLocation.membership_id == m.id))
    for lid in ids:
        ctx.db.add(MembershipLocation(tenant_id=ctx.tenant_id, membership_id=m.id, location_id=lid))
    audit(ctx.db, action="staff.locations_change", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="membership", entity_id=m.id,
          meta={"all_locations": body.all_locations, "location_ids": [str(i) for i in ids]}, ip=client_ip(request))
    ctx.db.commit()
