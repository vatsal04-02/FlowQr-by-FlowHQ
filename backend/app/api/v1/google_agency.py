"""Agency manager account: the client's consent screen, "check again" and "Stop FlowQR managing my profile" (services/google/agency.py).

The routes exist whether or not GOOGLE_AGENCY_MANAGER_ENABLED is on, but with it off status, consent and advance answer 404 exactly as an unknown path would, so nothing about today's
behaviour changes. `stop` is deliberately NOT behind the switch: a client who is managed must always be able to stop, whatever the switch says; it does nothing for a connection that has no
agency state.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.deps import TenantContext, ensure_verified, get_tenant_context, require_role
from app.models import GoogleAgencyAuthorization, GoogleConnection, GoogleConnectionStatus, Role
from app.services.google import agency

router = APIRouter(prefix="/google/agency", tags=["google-agency"])


class ConsentIn(BaseModel):
    connection_id: uuid.UUID
    agree: bool = False
    consent_version: str = ""
    scope: str | None = None  # the route the client chose: location (one profile) | business_group (several profiles of one Google business group)
    request_id: str | None = Field(default=None, max_length=64)  # replay protection: the same id never starts a second invitation


class StopIn(BaseModel):
    confirm: bool = False


def _on() -> None:
    if not agency.enabled():
        raise HTTPException(status_code=404, detail="Not Found")


def _conn(ctx: TenantContext, connection_id: uuid.UUID) -> GoogleConnection:
    conn = ctx.db.scalar(select(GoogleConnection).where(GoogleConnection.id == connection_id, GoogleConnection.tenant_id == ctx.tenant_id))
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    return conn


def _fail(exc: agency.AgencyError):
    if isinstance(exc, agency.AgencyDisabled):
        raise HTTPException(status_code=404, detail="Not Found")
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


@router.get("/status")
def status(ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    conns = ctx.db.scalars(select(GoogleConnection).where(GoogleConnection.tenant_id == ctx.tenant_id, GoogleConnection.status != GoogleConnectionStatus.disconnected)
                           .order_by(GoogleConnection.created_at)).all()
    return {"enabled": True, "consent_version": agency.CONSENT_VERSION, "consent_text": agency.consent_text(),
            "connections": [agency.status_view(ctx.db, c) for c in conns]}


@router.post("/consent")
def consent(body: ConsentIn, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
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
    _on()
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
