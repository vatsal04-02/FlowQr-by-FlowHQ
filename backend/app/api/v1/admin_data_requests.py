"""Platform-admin handling of export and deletion requests for a business that has no owner login. Nothing here runs by itself: every step is an administrator's explicit call, verified,
recorded and audited, and the destructive one needs the typed business name, an acknowledgement and a cooling-off period. See services/data_requests.py for the rules."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select

from app.core.deps import AuthContext, require_platform_admin
from app.core.rate_limit import client_ip, hit
from app.models import DataRequest, Tenant
from app.schemas.provisioning import DataRequestDeliveredIn, DataRequestExecuteIn, DataRequestIn, DataRequestReasonIn, DataRequestVerifyIn
from app.services import data_requests as svc
from app.services import provisioning as prov

router = APIRouter(prefix="/admin", tags=["platform-admin"])


def _fail(exc: prov.ProvisionError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.detail())


def _run(ctx: AuthContext, fn):
    """Run one step; on a refusal undo it and answer with the reason, on success commit and return the result."""
    try:
        result = fn()
    except prov.ProvisionError as exc:
        ctx.db.rollback()
        raise _fail(exc)
    ctx.db.commit()
    return result


@router.get("/tenants/{tenant_id}/data-requests")
def list_for_business(tenant_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    if ctx.db.get(Tenant, tenant_id) is None:
        raise HTTPException(status_code=404, detail="Business not found")
    rows = ctx.db.scalars(select(DataRequest).where(DataRequest.tenant_id == tenant_id).order_by(DataRequest.created_at.desc()).limit(20)).all()
    return {"items": [svc.serialize(ctx.db, r) for r in rows]}


@router.get("/data-requests")
def list_all(status: str | None = None, ctx: AuthContext = Depends(require_platform_admin)):
    """Every request, newest first, including those for businesses that have since been deleted."""
    q = select(DataRequest).order_by(DataRequest.created_at.desc()).limit(100)
    if status in ("open", "verified", "fulfilled", "rejected", "cancelled"):
        q = q.where(DataRequest.status == status)
    return {"items": [svc.serialize(ctx.db, r) for r in ctx.db.scalars(q).all()]}


@router.post("/tenants/{tenant_id}/data-requests", status_code=201)
def create_request(tenant_id: uuid.UUID, body: DataRequestIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Log a request to export or delete a business's data, made by the shopkeeper or someone speaking for them. Only for a business with no owner. Does nothing to the data."""
    if not hit(f"admin-datareq:{ctx.user.id}", 20, 3600):
        raise HTTPException(status_code=429, detail="Too many requests logged. Try again later.")
    t = ctx.db.get(Tenant, tenant_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Business not found")
    req = _run(ctx, lambda: svc.create(ctx.db, t, admin=ctx.user, kind=body.kind, requester_name=body.requester_name, requester_role=body.requester_role, received_via=body.received_via,
                                       requester_contact=body.requester_contact, note=body.note, ip=client_ip(request)))
    return svc.serialize(ctx.db, req)


@router.post("/data-requests/{request_id}/verify")
def verify_request(request_id: uuid.UUID, body: DataRequestVerifyIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    req = _run(ctx, lambda: svc.verify(ctx.db, svc.get(ctx.db, request_id), admin=ctx.user, method=body.method, contacted_on=body.contacted_on, note=body.note, ip=client_ip(request)))
    return svc.serialize(ctx.db, req)


@router.post("/data-requests/{request_id}/reject")
def reject_request(request_id: uuid.UUID, body: DataRequestReasonIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    req = _run(ctx, lambda: svc.reject(ctx.db, svc.get(ctx.db, request_id), admin=ctx.user, reason=body.reason, ip=client_ip(request)))
    return svc.serialize(ctx.db, req)


@router.post("/data-requests/{request_id}/cancel")
def cancel_request(request_id: uuid.UUID, body: DataRequestReasonIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    req = _run(ctx, lambda: svc.cancel(ctx.db, svc.get(ctx.db, request_id), admin=ctx.user, reason=body.reason, ip=client_ip(request)))
    return svc.serialize(ctx.db, req)


@router.get("/data-requests/{request_id}/export")
def download_export(request_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """The business's data as a ZIP (no secrets), for an administrator to hand to the verified requester. Only for a verified export request. Nothing is sent by the system."""
    if not hit(f"admin-datareq-export:{ctx.user.id}", 10, 3600):
        raise HTTPException(status_code=429, detail="Too many exports. Try again later.")
    data, _manifest, slug = _run(ctx, lambda: svc.generate_export(ctx.db, svc.get(ctx.db, request_id), admin=ctx.user, ip=client_ip(request)))
    return Response(data, media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="flowqr-export-{slug}.zip"', "Cache-Control": "private, no-store"})


@router.post("/data-requests/{request_id}/delivered")
def mark_delivered(request_id: uuid.UUID, body: DataRequestDeliveredIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    req = _run(ctx, lambda: svc.complete_export(ctx.db, svc.get(ctx.db, request_id), admin=ctx.user, delivery=body.delivery, note=body.note, ip=client_ip(request)))
    return svc.serialize(ctx.db, req)


@router.post("/data-requests/{request_id}/execute-deletion")
def execute_deletion(request_id: uuid.UUID, body: DataRequestExecuteIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """PERMANENTLY delete the business. Only for a verified deletion request past its cooling-off period, with the business name typed exactly and the consequences acknowledged."""
    if not hit(f"admin-datareq-delete:{ctx.user.id}", 5, 3600):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")
    return _run(ctx, lambda: svc.execute_deletion(ctx.db, svc.get(ctx.db, request_id), admin=ctx.user, confirm_name=body.confirm_name, acknowledge=body.acknowledge, ip=client_ip(request)))
