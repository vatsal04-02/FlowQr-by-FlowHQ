"""Agency manager account: the client's consent screen, "check again" and "Stop FlowQR managing my profile" (services/google/agency.py).

The routes exist whether or not GOOGLE_AGENCY_MANAGER_ENABLED is on, but with it off status, consent and advance answer 404 exactly as an unknown path would, so nothing about today's
behaviour changes. `stop` is deliberately NOT behind the switch: a client who is managed must always be able to stop, whatever the switch says; it does nothing for a connection that has no
agency state.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import settings
from app.core.deps import TenantContext, ensure_verified, get_tenant_context, require_role
from app.core.rate_limit import hit
from app.models import GoogleAgencyAuthorization, GoogleConnection, GoogleConnectionStatus, Role
from app.services.audit import audit
from app.services.google import agency, agency_journey

router = APIRouter(prefix="/google/agency", tags=["google-agency"])


class ConsentIn(BaseModel):
    connection_id: uuid.UUID
    agree: bool = False
    consent_version: str = ""
    scope: str | None = None  # the route the client chose: location (one profile) | business_group (several profiles of one Google business group)
    request_id: str | None = Field(default=None, max_length=64)  # replay protection: the same id never starts a second invitation


class JourneyStartIn(BaseModel):
    connection_id: uuid.UUID
    agree: bool = False
    consent_version: str = ""
    actions: list[str] = Field(default_factory=list, max_length=8)  # the permission categories the client ticked (agency.ACTION_CATEGORIES); reading is always included
    request_id: str | None = Field(default=None, max_length=64)


class StopIn(BaseModel):
    confirm: bool = False


def _on(tenant_id=None) -> None:
    if not agency.enabled() or (tenant_id is not None and not agency.tenant_allowed(tenant_id)):
        raise HTTPException(status_code=404, detail="Not Found")  # a business without an operator grant is told exactly what an unknown path says


def _conn(ctx: TenantContext, connection_id: uuid.UUID) -> GoogleConnection:
    conn = ctx.db.scalar(select(GoogleConnection).where(GoogleConnection.id == connection_id, GoogleConnection.tenant_id == ctx.tenant_id))
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    return conn


def _fail(exc: agency.AgencyError):
    if isinstance(exc, (agency.AgencyDisabled, agency.NotAnOperator, agency.TenantNotGranted)):
        raise HTTPException(status_code=404, detail="Not Found")  # a non-operator is told exactly what an unknown path says
    if isinstance(exc, agency.ConsentRequired):
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": "Please read and agree to what FlowQR will do before continuing."})
    if isinstance(exc, agency.ScopeInvalid):
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": str(exc)})
    if isinstance(exc, agency.LocationAlreadyManaged):
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)})
    if isinstance(exc, agency.ReplayDetected):
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)})
    if isinstance(exc, agency.NoAgencyAccount):
        raise HTTPException(status_code=503, detail={"code": "agency_unavailable", "message": "FlowQR cannot take this on right now. Nothing was changed. Please try again later."})
    raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)})


def _journey_on() -> None:
    """The guided onboarding is behind its own switch on top of the agency switch. Off: these routes answer exactly what an unknown path answers."""
    if not (agency.enabled() and settings.google_agency_self_service_enabled):
        raise HTTPException(status_code=404, detail="Not Found")


def _limit(ctx: TenantContext, what: str, limit: int, window: int) -> None:
    if not hit(f"agency-{what}:{ctx.tenant_id}", limit, window):
        raise HTTPException(status_code=429, detail={"code": "rate_limited", "message": "Too many attempts. Please wait a few minutes and try again."})


def _consent_block() -> dict:
    return {"version": agency.CONSENT_VERSION, "text": agency.consent_text(),
            "actions": [{"id": k, "label": v[0], "description": v[1], "required": v[2]} for k, v in agency.ACTION_CATEGORIES.items()]}


@router.get("/journey")
def journey(ctx: TenantContext = Depends(get_tenant_context)):
    """The self-service onboarding as one journey: state, the eight stages, what is blocking, the mapping checks, the sync status and a timeline. Read-only; sends nothing to Google."""
    _journey_on()
    if ctx.restricted:  # a member limited to some locations does not see the business-wide Google setup
        raise HTTPException(status_code=404, detail="Not Found")
    return {"offered": agency.tenant_allowed(ctx.tenant_id), "consent": _consent_block(), "can_act": ctx.membership.role in (Role.owner, Role.admin), "notice_hours": settings.google_agency_notice_hours,
            "removal_business_days": settings.google_agency_removal_business_days, **agency_journey.journey_for_tenant(ctx.db, ctx.tenant_id)}


@router.post("/journey/start")
def journey_start(body: JourneyStartIn, ctx: TenantContext = Depends(require_role(Role.admin))):
    """The client's explicit agreement (to the wording AND to each permission category), then the invitation and everything after it as far as it can go right now. Idempotent per request id."""
    _journey_on()
    _limit(ctx, "journey-start", 10, 3600)
    ensure_verified(ctx.user)
    conn = _conn(ctx, body.connection_id)
    routes = agency.available_routes(agency._selected_glocs(ctx.db, conn.id))
    if not routes["available"]:
        raise HTTPException(status_code=422, detail={"code": "scope_invalid", "message": routes["reason"] or "Select the business location first."})
    try:
        agency.record_consent(ctx.db, conn=conn, user=ctx.user, agree=body.agree, version=body.consent_version, scope=routes["available"][0], request_id=body.request_id, actions=body.actions)
        audit(ctx.db, action="google.agency.journey_started", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="google_connection", entity_id=conn.id, meta={"actions": body.actions})
        ctx.db.commit()
        agency.advance_connection(ctx.db, conn, force=True)
    except agency.AgencyError as exc:
        _fail(exc)
    ctx.db.refresh(conn)
    return agency_journey.journey_for_connection(ctx.db, conn)


@router.get("/status")
def status(ctx: TenantContext = Depends(get_tenant_context)):
    _on(ctx.tenant_id)
    conns = ctx.db.scalars(select(GoogleConnection).where(GoogleConnection.tenant_id == ctx.tenant_id, GoogleConnection.status != GoogleConnectionStatus.disconnected)
                           .order_by(GoogleConnection.created_at)).all()
    return {"enabled": True, "consent_version": agency.CONSENT_VERSION, "consent_text": agency.consent_text(),
            "connections": [agency.status_view(ctx.db, c) for c in conns]}


@router.post("/consent")
def consent(body: ConsentIn, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on(ctx.tenant_id)
    _limit(ctx, "consent", 10, 3600)
    ensure_verified(ctx.user)
    conn = _conn(ctx, body.connection_id)
    try:
        agency.record_consent(ctx.db, conn=conn, user=ctx.user, agree=body.agree, version=body.consent_version, scope=body.scope, request_id=body.request_id)
        agency.advance_connection(ctx.db, conn, force=True)
    except agency.AgencyError as exc:
        _fail(exc)
    ctx.db.refresh(conn)
    return agency.status_view(ctx.db, conn)


@router.post("/connections/{connection_id}/advance")
def advance(connection_id: uuid.UUID, ctx: TenantContext = Depends(require_role(Role.admin))):
    """"Check again": retries what is waiting and what needed attention. Idempotent."""
    _on(ctx.tenant_id)
    _limit(ctx, "advance", 30, 3600)
    conn = _conn(ctx, connection_id)
    try:
        agency.advance_connection(ctx.db, conn, force=True, retry=True)
    except agency.AgencyError as exc:
        _fail(exc)
    ctx.db.refresh(conn)
    return agency.status_view(ctx.db, conn)


@router.post("/connections/{connection_id}/stop")
def stop(connection_id: uuid.UUID, body: StopIn, ctx: TenantContext = Depends(require_role(Role.admin))):
    """"Stop FlowQR managing my profile": all work for this client stops now; FlowQR removes itself from Google and records the dates."""
    conn = _conn(ctx, connection_id)
    if not body.confirm:
        raise HTTPException(status_code=422, detail={"code": "confirm_required", "message": "Confirm that you want FlowQR to stop managing this profile."})
    if not ctx.db.scalar(select(GoogleAgencyAuthorization.id).where(GoogleAgencyAuthorization.connection_id == conn.id).limit(1)):
        raise HTTPException(status_code=404, detail="FlowQR is not managing this profile as an agency")
    agency.request_stop(ctx.db, conn, user=ctx.user)
    ctx.db.refresh(conn)
    return agency.status_view(ctx.db, conn)
