"""FlowHQ OPERATOR endpoints for the internal agency path (docs/audits/GOOGLE_PROJECT_ARCHITECTURE_OPTIONS.md, internal-only operation).

An operator is a signed-in, e-mail-verified person whose address is in GOOGLE_AGENCY_OPERATOR_EMAILS. This is deliberately NOT a business role: the operator needs no membership in any business, and
holds no right inside one. The operator can open or close the agency path for a business and read where each business stands. The operator cannot record a client's consent (only the business's own
administrator can) and never sees a token, a review or any Google content. Everyone else gets what an unknown path gives: 404.
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from app.core.config import settings
from app.core.db import set_rls_context
from app.core.deps import AuthContext, get_auth_context
from app.models import GoogleAgencyAuthorization, GoogleAgencyTenantGrant, GoogleConnection, Tenant
from app.core.rate_limit import hit
from app.services.audit import audit
from app.services.google import agency, agency_activation, agency_journey
from app.core.rate_limit import client_ip

router = APIRouter(prefix="/agency-ops", tags=["agency-operators"])


def require_operator(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
    email = (auth.user.email or "").strip().lower()
    if not agency.enabled() or email not in settings.google_agency_operator_set:
        raise HTTPException(status_code=404, detail="Not Found")
    if settings.require_verified_email and not auth.user.email_verified_at:
        raise HTTPException(status_code=404, detail="Not Found")
    set_rls_context(auth.db, bypass=True)  # the operator reads across businesses to open or close the path, and nothing else
    return auth


class GrantIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: str | None = Field(default=None, max_length=300)


@router.get("/readiness")
def readiness(ctx: AuthContext = Depends(require_operator)):
    """The same read-only checklist as `google-agency-activation-check`: each precondition PASS or BLOCK, and who has to act."""
    items = agency_activation.lines(ctx.db)
    return {"ready": agency_activation.ready(items), "lines": [{"name": i.name, "status": i.status, "who": i.who, "detail": i.detail} for i in items]}


@router.get("/tenants")
def tenants(ctx: AuthContext = Depends(require_operator)):
    """Every business that has a Google connection: whether the agency path is open for it, and the state of its authorizations (counts and statuses only)."""
    rows = []
    for t in ctx.db.scalars(select(Tenant).join(GoogleConnection, GoogleConnection.tenant_id == Tenant.id).distinct().order_by(Tenant.name)):
        grant = ctx.db.scalar(select(GoogleAgencyTenantGrant).where(GoogleAgencyTenantGrant.tenant_id == t.id, GoogleAgencyTenantGrant.revoked_at.is_(None)))
        by_status = dict(ctx.db.execute(select(GoogleAgencyAuthorization.status, func.count()).where(GoogleAgencyAuthorization.tenant_id == t.id).group_by(GoogleAgencyAuthorization.status)).all())
        modes = [m for (m,) in ctx.db.execute(select(GoogleConnection.auth_mode).where(GoogleConnection.tenant_id == t.id)).all()]
        rows.append({"tenant_id": str(t.id), "name": t.name, "agency_path_open": grant is not None, "granted_by": grant.granted_by_email if grant else None,
                     "granted_at": grant.granted_at if grant else None, "authorizations": by_status, "connection_modes": modes})
    return {"tenants": rows}


@router.post("/tenants/{tenant_id}/grant", status_code=201)
def grant(tenant_id: uuid.UUID, body: GrantIn, request: Request, ctx: AuthContext = Depends(require_operator)):
    if ctx.db.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Not Found")
    row = agency.grant_tenant(tenant_id, operator_email=ctx.user.email, note=body.note)
    audit(ctx.db, action="agency_ops.grant", user_id=ctx.user.id, tenant_id=tenant_id, entity_type="google_agency_tenant_grant", entity_id=row.id, ip=client_ip(request))
    ctx.db.commit()
    return {"tenant_id": str(tenant_id), "agency_path_open": True, "granted_by": row.granted_by_email, "granted_at": row.granted_at}


@router.post("/tenants/{tenant_id}/revoke")
def revoke(tenant_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_operator)):
    changed = agency.revoke_tenant_grant(tenant_id, operator_email=ctx.user.email)
    audit(ctx.db, action="agency_ops.revoke", user_id=ctx.user.id, tenant_id=tenant_id, entity_type="google_agency_tenant_grant", meta={"changed": changed}, ip=client_ip(request))
    ctx.db.commit()
    return {"tenant_id": str(tenant_id), "agency_path_open": False, "changed": changed}


# ------------------------------------------------------------------ the operator's view of every business's onboarding (read-only, except "check again")
def _operator_row(db, conn: GoogleConnection, *, compact: bool) -> dict:
    j = agency_journey.journey_for_connection(db, conn, operator=True, compact=compact)
    t = db.get(Tenant, conn.tenant_id)
    j["tenant_id"], j["tenant_name"] = str(conn.tenant_id), t.name if t else None
    j["grant_open"] = bool(db.scalar(select(func.count()).select_from(GoogleAgencyTenantGrant).where(GoogleAgencyTenantGrant.tenant_id == conn.tenant_id, GoogleAgencyTenantGrant.revoked_at.is_(None))))
    return j


@router.get("/journeys")
def journeys(state: str | None = None, tenant_id: uuid.UUID | None = None, limit: int = 100, ctx: AuthContext = Depends(require_operator)):
    """Every connection that has an agency authorization: the business, the selected Google location, where the onboarding stands (one of the journey states), the consent given, the last
    synchronization and its failures, and any revocation. Never a token, a review or other Google content. `state` filters by journey state."""
    if state is not None and state not in agency_journey.JOURNEY_STATES:
        raise HTTPException(status_code=422, detail="Unknown state")
    q = select(GoogleConnection).join(GoogleAgencyAuthorization, GoogleAgencyAuthorization.connection_id == GoogleConnection.id)
    if tenant_id:
        q = q.where(GoogleConnection.tenant_id == tenant_id)
    q = q.group_by(GoogleConnection.id).order_by(func.max(GoogleAgencyAuthorization.updated_at).desc()).limit(max(1, min(limit, 300)))
    rows = [_operator_row(ctx.db, c, compact=True) for c in ctx.db.scalars(q)]
    if state:
        rows = [r for r in rows if r["state"] == state]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    return {"states": list(agency_journey.JOURNEY_STATES), "counts": counts, "journeys": rows}


@router.get("/journeys/{connection_id}")
def journey_detail(connection_id: uuid.UUID, ctx: AuthContext = Depends(require_operator)):
    """One business in full: the steps, the mapping checks, the consent (version, categories, who, when), the audit timeline and the failure codes."""
    conn = ctx.db.get(GoogleConnection, connection_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Not Found")
    return _operator_row(ctx.db, conn, compact=False)


@router.post("/journeys/{connection_id}/advance")
def journey_advance(connection_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_operator)):
    """Run the next steps again for one business ("check again"). It records no consent and changes no permission: it only retries what the business already agreed to. Rate limited."""
    if not hit(f"agency-ops-advance:{ctx.user.id}", 60, 3600):
        raise HTTPException(status_code=429, detail="Too many retries. Wait a few minutes.")
    conn = ctx.db.get(GoogleConnection, connection_id)
    if conn is None:
        raise HTTPException(status_code=404, detail="Not Found")
    try:
        agency.advance_connection(ctx.db, conn, force=True, retry=True)
    except agency.AgencyError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)})
    audit(ctx.db, action="agency_ops.advance", user_id=ctx.user.id, tenant_id=conn.tenant_id, entity_type="google_connection", entity_id=conn.id, ip=client_ip(request))
    ctx.db.commit()
    ctx.db.refresh(conn)
    return _operator_row(ctx.db, conn, compact=False)
