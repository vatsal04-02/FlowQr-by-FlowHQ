"""Platform admin: the people behind the customers. A directory of login accounts, a "login check" for one email, and support actions.

Rules: platform admins only; every lookup and every action is written to the audit log; password hashes, session tokens and reset
tokens are never returned. The login check mirrors the real login rules (auth.py) so "can log in" means what it says.
"""
import re
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update

from app.core.config import settings
from app.core.deps import AuthContext, require_platform_admin
from app.core.rate_limit import client_ip, hit
from app.core.security import hash_token, new_token
from app.models import AuditLog, AuthSession, Membership, PasswordResetToken, Subscription, Tenant, User
from app.models.base import utcnow
from app.services.audit import audit
from app.services.mailer import send_email

router = APIRouter(prefix="/admin/users", tags=["admin"])
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _live_sessions(db, user_id: uuid.UUID) -> int:
    return db.scalar(select(func.count()).select_from(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None), AuthSession.expires_at > utcnow())) or 0


def _row(db, u: User, businesses: int | None = None) -> dict:
    return {
        "id": u.id, "email": u.email, "full_name": u.full_name, "phone": u.phone, "is_active": u.is_active, "is_platform_admin": u.is_platform_admin,
        "email_verified": u.email_verified_at is not None, "has_password": bool(u.password_hash), "google_linked": bool(u.google_sub),
        "last_login_at": u.last_login_at, "created_at": u.created_at,
        "businesses": businesses if businesses is not None else db.scalar(select(func.count()).select_from(Membership).where(Membership.user_id == u.id)),
        "live_sessions": _live_sessions(db, u.id),
    }


def _login_verdict(db, u: User | None) -> dict:
    """Can this person log in right now, and if not, exactly why. Mirrors auth.login: it needs an active account and a password
    (Google-only accounts sign in with Google instead). Suspended businesses do not block the login; they block what happens after."""
    if u is None:
        return {"can_log_in": False, "reasons": ["No account uses this email. They may have registered with a different address, or not registered yet."], "notes": []}
    reasons, notes = [], []
    if not u.is_active:
        reasons.append("The account is deactivated by FlowQR staff, so every login is refused.")
    if not u.password_hash and not u.google_sub:
        reasons.append("The account has no password and no Google sign-in, so there is nothing to log in with. Send a password reset.")
    elif not u.password_hash:
        notes.append("Google-only account: they sign in with \"Continue with Google\". Email and password login is off until they set a password.")
    if not u.email_verified_at:
        notes.append("Email not verified. They can still log in, but inviting staff, connecting Google and billing stay locked until they verify.")
    ms = db.execute(select(Membership, Tenant).join(Tenant, Tenant.id == Membership.tenant_id).where(Membership.user_id == u.id)).all()
    if not ms and not u.is_platform_admin:
        notes.append("They belong to no business, so after logging in they land on onboarding.")
    for m, t in ms:
        if t.suspended_at or not t.is_active:
            notes.append(f"{t.name} is suspended: they can log in but will see the suspended screen for that business.")
        elif t.deletion_scheduled_for:
            notes.append(f"{t.name} is scheduled for deletion on {t.deletion_scheduled_for:%d %b %Y}.")
    return {"can_log_in": not reasons, "reasons": reasons, "notes": notes}


@router.get("")
def list_users(ctx: AuthContext = Depends(require_platform_admin), search: str | None = None, state: str | None = Query(None, pattern="^(active|deactivated|unverified|google_only|no_login|admin)$"),
               limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    q = select(User)
    if search and search.strip():
        like = "%" + search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        q = q.where(or_(User.email.ilike(like, escape="\\"), User.full_name.ilike(like, escape="\\"), User.phone.ilike(like, escape="\\"),
                        User.id.in_(select(Membership.user_id).join(Tenant, Tenant.id == Membership.tenant_id).where(Tenant.name.ilike(like, escape="\\")))))
    if state == "active":
        q = q.where(User.is_active.is_(True))
    elif state == "deactivated":
        q = q.where(User.is_active.is_(False))
    elif state == "unverified":
        q = q.where(User.email_verified_at.is_(None))
    elif state == "google_only":
        q = q.where(User.password_hash.is_(None), User.google_sub.is_not(None))
    elif state == "no_login":
        q = q.where(User.password_hash.is_(None), User.google_sub.is_(None))
    elif state == "admin":
        q = q.where(User.is_platform_admin.is_(True))
    total = ctx.db.scalar(select(func.count()).select_from(q.subquery()))
    users = ctx.db.scalars(q.order_by(User.created_at.desc()).limit(limit).offset(offset)).all()
    counts = dict(ctx.db.execute(select(Membership.user_id, func.count()).where(Membership.user_id.in_([u.id for u in users])).group_by(Membership.user_id)).all()) if users else {}
    biz = {}
    if users:
        for uid, name in ctx.db.execute(select(Membership.user_id, Tenant.name).join(Tenant, Tenant.id == Membership.tenant_id).where(Membership.user_id.in_([u.id for u in users])).order_by(Tenant.name)):
            biz.setdefault(uid, []).append(name)
    totals = {
        "all": ctx.db.scalar(select(func.count()).select_from(User)), "unverified": ctx.db.scalar(select(func.count()).select_from(User).where(User.email_verified_at.is_(None))),
        "deactivated": ctx.db.scalar(select(func.count()).select_from(User).where(User.is_active.is_(False))),
        "active_30d": ctx.db.scalar(select(func.count()).select_from(User).where(User.last_login_at > utcnow() - timedelta(days=30))),
    }
    return {"total": total, "totals": totals, "items": [_row(ctx.db, u, counts.get(u.id, 0)) | {"business_names": biz.get(u.id, [])[:3]} for u in users]}


class LookupIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)


def _detail(ctx: AuthContext, u: User) -> dict:
    db = ctx.db
    ms = db.execute(select(Membership, Tenant).join(Tenant, Tenant.id == Membership.tenant_id).where(Membership.user_id == u.id).order_by(Tenant.name)).all()
    subs = {s.tenant_id: s for s in db.scalars(select(Subscription).where(Subscription.tenant_id.in_([t.id for _, t in ms])))} if ms else {}
    sessions = db.scalars(select(AuthSession).where(AuthSession.user_id == u.id, AuthSession.revoked_at.is_(None), AuthSession.expires_at > utcnow()).order_by(AuthSession.created_at.desc()).limit(10)).all()
    logins = db.scalars(select(AuditLog).where(AuditLog.user_id == u.id, AuditLog.action.in_(("auth.login", "auth.login_google", "auth.logout", "auth.password_reset", "auth.password_change"))).order_by(AuditLog.created_at.desc()).limit(15)).all()
    return {
        "user": _row(db, u), "login": _login_verdict(db, u),
        "businesses": [{"tenant_id": t.id, "name": t.name, "role": m.role.value, "suspended": bool(t.suspended_at or not t.is_active), "plan": subs[t.id].plan if t.id in subs else None,
                        "subscription_status": subs[t.id].status if t.id in subs else None} for m, t in ms],
        # no tokens, only what an admin needs to see: when, from where, on what device
        "sessions": [{"started": s.created_at, "expires": s.expires_at, "ip": s.ip, "device": (s.user_agent or "")[:120]} for s in sessions],
        "recent_activity": [{"action": a.action, "at": a.created_at, "ip": a.ip} for a in logins],
    }


@router.post("/lookup")
def lookup(body: LookupIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Login check: does an account exist for this email, and can it log in? Audited, and rate-limited per admin."""
    email = body.email.strip().lower()
    if not EMAIL.match(email):
        raise HTTPException(status_code=422, detail="That doesn't look like an email address.")
    if not hit(f"admin-lookup:{ctx.user.id}", 60, 60):
        raise HTTPException(status_code=429, detail="Too many lookups. Wait a minute.")
    u = ctx.db.scalar(select(User).where(User.email == email))
    audit(ctx.db, action="admin.user_lookup", user_id=ctx.user.id, entity_type="user", entity_id=u.id if u else None, meta={"email": email, "found": bool(u)}, ip=client_ip(request))
    ctx.db.commit()
    if u is None:
        # also say whether the email was INVITED to a business, the other common reason someone "can't log in"
        from app.models import Invitation
        inv = ctx.db.execute(select(Invitation, Tenant).join(Tenant, Tenant.id == Invitation.tenant_id).where(func.lower(Invitation.email) == email, Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None), Invitation.expires_at > utcnow())).all()
        return {"exists": False, "email": email, "login": _login_verdict(ctx.db, None),
                "pending_invitations": [{"business": t.name, "role": i.role.value, "expires_at": i.expires_at} for i, t in inv]}
    return {"exists": True, "email": email} | _detail(ctx, u)


@router.get("/{user_id}")
def user_detail(user_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    u = ctx.db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return _detail(ctx, u)


def _user(ctx: AuthContext, user_id: uuid.UUID) -> User:
    u = ctx.db.get(User, user_id)
    if not u:
        raise HTTPException(status_code=404, detail="User not found")
    return u


@router.post("/{user_id}/verify-email", status_code=204)
def verify_email(user_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Mark the email verified (for example after confirming the person by phone). Audited."""
    u = _user(ctx, user_id)
    if u.email_verified_at is None:
        u.email_verified_at = utcnow()
    audit(ctx.db, action="admin.user_verify_email", user_id=ctx.user.id, entity_type="user", entity_id=u.id, ip=client_ip(request))
    ctx.db.commit()


@router.post("/{user_id}/revoke-sessions")
def revoke_sessions(user_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Sign this person out everywhere. They can log in again straight away."""
    u = _user(ctx, user_id)
    res = ctx.db.execute(update(AuthSession).where(AuthSession.user_id == u.id, AuthSession.revoked_at.is_(None)).values(revoked_at=utcnow()))
    audit(ctx.db, action="admin.user_revoke_sessions", user_id=ctx.user.id, entity_type="user", entity_id=u.id, meta={"sessions": res.rowcount}, ip=client_ip(request))
    ctx.db.commit()
    return {"revoked": res.rowcount}


@router.post("/{user_id}/send-reset")
def send_reset(user_id: uuid.UUID, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    """Email the person a password-reset link (the same link as "Forgot password"). The admin never sees or sets the password."""
    u = _user(ctx, user_id)
    if not u.is_active:
        raise HTTPException(status_code=409, detail="This account is deactivated. Reactivate it first.")
    if not hit(f"admin-reset:{u.id}", 3, 3600):
        raise HTTPException(status_code=429, detail="A reset was already sent a few times this hour. Try again later.")
    token, now = new_token(), utcnow()
    ctx.db.add(PasswordResetToken(user_id=u.id, token_hash=hash_token(token), created_at=now, expires_at=now + timedelta(minutes=settings.password_reset_ttl_minutes)))
    audit(ctx.db, action="admin.user_send_reset", user_id=ctx.user.id, entity_type="user", entity_id=u.id, ip=client_ip(request))
    ctx.db.commit()
    sent = send_email(u.email, "Reset your FlowQR password", f"A FlowQR administrator started a password reset for your account.\nOpen this link to choose a new password:\n{settings.frontend_url}/reset-password?token={token}")
    return {"sent": bool(sent), "to": u.email, "expires_minutes": settings.password_reset_ttl_minutes}
