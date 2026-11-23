"""Account lifecycle for the business owner: data export, deletion, and the facts the public legal pages show."""
import logging
from datetime import datetime

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db, set_rls_context
from app.core.deps import AuthContext, TenantContext, get_auth_context, get_tenant_context, require_role
from app.core.rate_limit import client_ip, hit, limit_by_ip
from app.core.security import verify_password
from app.models import Role
from app.models.base import utcnow
from app.services import account as svc
from app.services import account_mail
from app.services.audit import audit

router = APIRouter(tags=["account"])
log = logging.getLogger("flowqr.account")
ACTIVE_PAID = {"active", "past_due", "pending", "authenticated"}


@router.get("/legal/info")
def legal_info():
    """Public. What the privacy, terms and data-deletion pages show. Nothing is invented: an unset support email is reported as unset."""
    return {"company": settings.legal_company_name, "support_email": settings.support_email or None,
            "company_address": settings.legal_company_address or None, "grievance_officer": settings.grievance_officer_name or None,
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
    account_mail.export_downloaded(ctx.db, to=ctx.user.email, name=ctx.user.full_name, business=ctx.tenant.name, when=utcnow(), tenant_id=ctx.tenant_id, user_id=ctx.user.id)  # says THAT it happened, never what is in it
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
    if not hit(f"deltenant:{ctx.user.id}", 5, 3600):  # the password is checked below: do not let a stolen session guess it without limit
        raise HTTPException(status_code=429, detail="You have asked too many times. Try again later.")
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
    account_mail.business_deletion_requested(ctx.db, to=ctx.user.email, name=ctx.user.full_name, business=t.name, scheduled_for=when, tenant_id=ctx.tenant_id, user_id=ctx.user.id)  # once: a repeat returns above
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


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Deleting your OWN account (not the business). See services/account.py for the whole life cycle and what it never does.
# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
class SelfDeleteIn(BaseModel):
    confirm_email: str = Field(min_length=3, max_length=254)  # the person types their own email address
    password: str | None = Field(default=None, max_length=200)


class ConfirmLinkIn(BaseModel):
    token: str = Field(min_length=20, max_length=200)


def _self_error(exc: svc.SelfDeletionError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail={"code": exc.code, "message": str(exc), "businesses": exc.businesses})


@router.get("/account/me/deletion")
def my_deletion_status(ctx: AuthContext = Depends(get_auth_context)):
    """Where deleting my own account stands: none, awaiting_confirmation (link emailed), or scheduled (with the date). Also what would block it."""
    return svc.self_deletion_state(ctx.db, ctx.user)


@router.post("/account/me/deletion")
def request_my_deletion(body: SelfDeleteIn, request: Request, ctx: AuthContext = Depends(get_auth_context)):
    """Ask to delete my own account. Needs my email typed, and either my password or (Google-only accounts) a sign-in from the last few minutes. Emails a single-use confirmation link; nothing is deleted yet."""
    user = ctx.user
    if not hit(f"mydel:{user.id}", 5, 3600):
        raise HTTPException(status_code=429, detail="You have asked too many times. Try again later.")
    if body.confirm_email.strip().lower() != user.email:
        raise HTTPException(status_code=422, detail="Type your own email address exactly as shown to confirm.")
    if user.has_local_login:
        if not (body.password and verify_password(body.password, user.password_hash)):
            raise HTTPException(status_code=403, detail={"code": "reauth_required", "message": "That password is not correct."})
    elif ctx.session.created_at < utcnow() - timedelta(minutes=settings.reauth_window_minutes):
        raise HTTPException(status_code=403, detail={"code": "reauth_required", "message": "For your security, sign in again, then try straight away."})
    try:
        token = svc.request_self_deletion(ctx.db, user)
    except svc.SelfDeletionError as exc:
        raise _self_error(exc)
    if token:
        link = f"{settings.frontend_url.rstrip('/')}/confirm-account-deletion?token={token}"
        audit(ctx.db, action="account.user_deletion_requested", user_id=user.id, entity_type="user", entity_id=user.id, ip=client_ip(request))
        account_mail.deletion_requested(ctx.db, to=user.email, name=user.full_name, link=link, user_id=user.id)
    ctx.db.commit()
    return svc.self_deletion_state(ctx.db, user)


@router.post("/account/me/deletion/confirm", status_code=204, dependencies=[Depends(limit_by_ip("mydel-confirm", 10, 300))])
def confirm_my_deletion(body: ConfirmLinkIn, request: Request, db: Session = Depends(get_db)):
    """The emailed link. Works once, expires, needs no sign-in (it proves the mailbox, like a password reset). Signs every session out and schedules the deletion."""
    try:
        user = svc.confirm_self_deletion(db, body.token)
    except svc.SelfDeletionError as exc:
        raise _self_error(exc)
    audit(db, action="account.user_deletion_confirmed", user_id=user.id, entity_type="user", entity_id=user.id,
          meta={"scheduled_for": user.deletion_scheduled_for.isoformat()}, ip=client_ip(request))
    db.commit()


@router.delete("/account/me/deletion")
def cancel_my_deletion(request: Request, ctx: AuthContext = Depends(get_auth_context)):
    """Cancel deleting my own account (a pending link, or a confirmed deletion still inside the grace period)."""
    set_rls_context(ctx.db, bypass=True)  # a person-level entry has no business (tenant) attached, like the other account routes
    if ctx.user.deletion_requested_at or ctx.user.deletion_scheduled_for:
        svc.cancel_self_deletion(ctx.user)
        audit(ctx.db, action="account.user_deletion_cancelled", user_id=ctx.user.id, entity_type="user", entity_id=ctx.user.id, ip=client_ip(request))
        ctx.db.commit()
    return svc.self_deletion_state(ctx.db, ctx.user)
