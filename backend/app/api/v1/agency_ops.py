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
from app.services.audit import audit
from app.services.google import agency, agency_activation
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
