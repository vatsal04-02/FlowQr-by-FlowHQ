"""Account lifecycle for the business owner: data export, deletion, and the facts the public legal pages show."""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.deps import TenantContext, get_tenant_context, require_role
from app.core.rate_limit import client_ip, hit
from app.core.security import verify_password
from app.models import Role
from app.services import account as svc
from app.services.audit import audit

router = APIRouter(tags=["account"])
log = logging.getLogger("flowqr.account")
ACTIVE_PAID = {"active", "past_due", "pending", "authenticated"}


@router.get("/legal/info")
def legal_info():
    """Public. What the privacy, terms and data-deletion pages show. Nothing is invented: an unset support email is reported as unset."""
    return {"company": settings.legal_company_name, "support_email": settings.support_email or None,
            "deletion_grace_days": settings.account_deletion_grace_days, "review_session_retention_days": settings.review_session_retention_days,
            "ai_provider": settings.ai_provider if settings.ai_configured else None}


@router.get("/account/export")
def export_data(request: Request, ctx: TenantContext = Depends(require_role(Role.owner))):
    """Everything FlowQR holds for this business, as a ZIP of JSON files. Owner only; never includes secrets."""
    if not hit(f"export:{ctx.tenant_id}", 3, 3600):
        raise HTTPException(status_code=429, detail="You can export your data 3 times an hour. Try again later.")
    data, manifest = svc.build_export(ctx.db, ctx.tenant)
    audit(ctx.db, action="account.export", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="tenant", entity_id=ctx.tenant_id,
          meta={"files": len(manifest["files"]), "bytes": len(data)}, ip=client_ip(request))
    ctx.db.commit()
    return Response(data, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="flowqr-export-{ctx.tenant.slug}.zip"', "Cache-Control": "private, no-store"})


class DeleteIn(BaseModel):
    confirm_name: str = Field(min_length=1, max_length=200)  # the business name, typed
    password: str | None = Field(default=None, max_length=200)


def _status(t) -> dict:
    return {"requested": t.deletion_scheduled_for is not None, "requested_at": t.deletion_requested_at, "scheduled_for": t.deletion_scheduled_for,
            "grace_days": settings.account_deletion_grace_days}


@router.get("/account/deletion")
def deletion_status(ctx: TenantContext = Depends(get_tenant_context)):
    return _status(ctx.tenant)


@router.post("/account/deletion")
def request_deletion(body: DeleteIn, request: Request, ctx: TenantContext = Depends(require_role(Role.owner))):
    """Schedule deletion of the whole business. Nothing is deleted now: the owner has a grace period to cancel."""
    t = ctx.tenant
    if body.confirm_name.strip() != t.name:
        raise HTTPException(status_code=422, detail="Type the business name exactly as shown to confirm.")
    if ctx.user.has_local_login and not (body.password and verify_password(body.password, ctx.user.password_hash)):
        raise HTTPException(status_code=403, detail="That password is not correct.")
    from sqlalchemy import select

    from app.models import Subscription
    sub = ctx.db.scalar(select(Subscription).where(Subscription.tenant_id == ctx.tenant_id))
    if sub and sub.razorpay_subscription_id and sub.status in ACTIVE_PAID:
        raise HTTPException(status_code=409, detail={"code": "cancel_subscription_first", "message": "Cancel your paid subscription first (Subscription page), then delete the account, so you are not charged again."})
    if t.deletion_scheduled_for:
        return _status(t)
    when = svc.schedule_deletion(ctx.db, t)
    audit(ctx.db, action="account.deletion_requested", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="tenant", entity_id=ctx.tenant_id,
          meta={"scheduled_for": when.isoformat()}, ip=client_ip(request))
    ctx.db.commit()
    return _status(t)


@router.delete("/account/deletion")
def cancel_deletion(request: Request, ctx: TenantContext = Depends(require_role(Role.owner))):
    """Cancel a pending deletion. Everything is exactly as it was."""
    if ctx.tenant.deletion_scheduled_for:
        svc.cancel_deletion(ctx.tenant)
        audit(ctx.db, action="account.deletion_cancelled", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="tenant", entity_id=ctx.tenant_id, ip=client_ip(request))
        ctx.db.commit()
    return _status(ctx.tenant)
