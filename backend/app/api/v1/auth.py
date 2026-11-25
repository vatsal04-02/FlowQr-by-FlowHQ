from datetime import timedelta

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db, set_rls_context
from app.core.deps import CSRF_COOKIE, SESSION_COOKIE, AuthContext, get_auth_context
from app.core.rate_limit import client_ip, hit, limit_by_ip
from app.core.security import (
    DUMMY_HASH, hash_password, hash_token, needs_rehash, new_token, verify_password,
)
from app.models import AuthSession, EmailVerificationToken, Membership, PasswordResetToken, Tenant, User
from app.models.base import utcnow
from app.schemas.auth import (
    ChangePasswordIn, LoginIn, MeOut, MembershipOut, PasswordResetConfirmIn, PasswordResetRequestIn,
    ProfileUpdateIn, RegisterIn, SetPasswordIn, TenantOut, UserOut, VerifyEmailIn,
)
from app.services import registration
from app.services.audit import audit
from app.services.mailer import send_email

router = APIRouter(prefix="/auth", tags=["auth"])


def _start_session(db: Session, user: User, request: Request, response: Response) -> AuthSession:
    token = new_token()
    now = utcnow()
    set_rls_context(db, bypass=True)
    memberships = list(db.scalars(select(Membership).where(Membership.user_id == user.id)))
    # A platform admin can see every business, so their sign-in is short-lived (they sign in again each working day).
    ttl_hours = min(settings.session_ttl_hours, settings.admin_session_ttl_hours) if user.is_platform_admin else settings.session_ttl_hours
    sess = AuthSession(
        user_id=user.id,
        token_hash=hash_token(token),
        csrf_token=new_token(24),
        active_tenant_id=memberships[0].tenant_id if memberships else None,
        ip=client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:300],
        created_at=now,
        expires_at=now + timedelta(hours=ttl_hours),
    )
    db.add(sess)
    db.flush()
    max_age = ttl_hours * 3600
    common = dict(max_age=max_age, secure=settings.cookie_secure, samesite="lax", path="/",
                  domain=settings.cookie_domain or None)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)
    response.set_cookie(CSRF_COOKIE, sess.csrf_token, httponly=False, **common)
    return sess


def build_me(db: Session, user: User, sess: AuthSession) -> MeOut:
    set_rls_context(db, bypass=True)
    rows = db.execute(
        select(Membership, Tenant).join(Tenant, Tenant.id == Membership.tenant_id).where(Membership.user_id == user.id)
    ).all()
    set_rls_context(db)
    return MeOut(
        user=UserOut.model_validate(user),
        memberships=[MembershipOut(tenant=TenantOut.model_validate(t), role=m.role) for m, t in rows],
        active_tenant_id=sess.active_tenant_id,
        csrf_token=sess.csrf_token,
        integrations={
            "google_configured": settings.google_configured,
            "ai_configured": settings.ai_configured,
            "public_card_base_url": settings.public_card_base_url,
            "whatsapp_enabled": settings.whatsapp_enabled,
        },
    )


def send_verification(db: Session, user: User) -> bool:
    token = new_token()
    now = utcnow()
    db.add(EmailVerificationToken(user_id=user.id, token_hash=hash_token(token), created_at=now,
                                  expires_at=now + timedelta(hours=settings.email_verification_ttl_hours)))
    db.flush()
    link = f"{settings.frontend_url}/verify-email?token={token}"
    return send_email(user.email, "Verify your FlowQR email", f"Welcome to FlowQR! Confirm your email address:\n{link}\n\nIf you didn't create an account, ignore this message.")


@router.post("/register", response_model=MeOut, status_code=201,
             dependencies=[Depends(limit_by_ip("auth", settings.rl_auth_per_minute, 60)), Depends(limit_by_ip("register-hour", settings.rl_register_per_hour, 3600))])
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.lower()
    registration.gate_new_account(db, request, email, "password")  # FIRST: a refused address never learns whether it is listed or already registered
    if not body.age_confirmed:  # validated here, not only in the form: a direct API call without the declaration creates nothing
        raise HTTPException(status_code=422, detail={"code": "age_declaration_required", "message": "Please tick the box to confirm you are 18 or older and agree to the privacy policy and terms."})
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(
        email=email, password_hash=hash_password(body.password), full_name=body.full_name.strip(),
        phone=body.phone,  # NOT a platform admin yet: that is granted only once the address is proven (see verify_email)
        age_confirmed_at=utcnow(), age_declaration_version=registration.AGE_DECLARATION_VERSION,
    )
    db.add(user)
    db.flush()
    sess = _start_session(db, user, request, response)
    set_rls_context(db, bypass=True)
    send_verification(db, user)
    audit(db, action="auth.register", user_id=user.id, entity_type="user", entity_id=user.id, ip=client_ip(request),
          meta={"age_declared": True, "privacy_consent": True, "age_declaration_version": registration.AGE_DECLARATION_VERSION})
    db.commit()
    return build_me(db, user, sess)


@router.post("/login", response_model=MeOut, dependencies=[Depends(limit_by_ip("auth", settings.rl_auth_per_minute, 60))])
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    email = body.email.lower()
    if not hit(f"login-email:{email}", 10, 900):
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a few minutes.")
    user = db.scalar(select(User).where(User.email == email))
    # Google-only accounts have no hash: verify against the dummy so timing and the 401 are identical to a wrong password.
    ok = verify_password(body.password, user.password_hash if user and user.password_hash else DUMMY_HASH)
    if not user or not user.password_hash or not ok or not user.is_active:
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    user.last_login_at = utcnow()
    sess = _start_session(db, user, request, response)
    set_rls_context(db, bypass=True)
    audit(db, action="auth.login", user_id=user.id, entity_type="user", entity_id=user.id, ip=client_ip(request))
    db.commit()
    return build_me(db, user, sess)


@router.get("/registration")
def registration_mode():
    """Public. Only the MODE (closed, allowlist or open), so the sign-up page can say so before someone types a password. Never the list, never anything about an address. The backend
    enforces it regardless of what this page shows."""
    return {"mode": registration.mode()}


@router.get("/providers")
def sign_in_providers():
    """Public. Which optional ways to sign in this server really offers, so the login and sign-up pages show "Continue with Google" only when it can work. A boolean and nothing else:
    never a client id, a secret or an address. Email and password is always on and does not depend on any of this."""
    return {"google": settings.google_login_configured}


@router.post("/logout", status_code=204)
def logout(response: Response, ctx: AuthContext = Depends(get_auth_context)):
    ctx.session.revoked_at = utcnow()
    set_rls_context(ctx.db, bypass=True)
    audit(ctx.db, action="auth.logout", user_id=ctx.user.id)
    ctx.db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/", domain=settings.cookie_domain or None)
    response.delete_cookie(CSRF_COOKIE, path="/", domain=settings.cookie_domain or None)


@router.get("/me", response_model=MeOut)
def me(ctx: AuthContext = Depends(get_auth_context)):
    return build_me(ctx.db, ctx.user, ctx.session)


@router.patch("/profile", response_model=UserOut)
def update_profile(body: ProfileUpdateIn, ctx: AuthContext = Depends(get_auth_context)):
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(ctx.user, k, v)
    ctx.db.commit()
    return ctx.user


@router.post("/select-tenant", status_code=204)
def select_tenant(tenant_id: str, ctx: AuthContext = Depends(get_auth_context)):
    import uuid as _uuid

    try:
        tid = _uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid tenant")
    set_rls_context(ctx.db, bypass=True)
    m = ctx.db.scalar(select(Membership).where(Membership.user_id == ctx.user.id, Membership.tenant_id == tid))
    if not m:
        raise HTTPException(status_code=403, detail="No access to this business")
    ctx.session.active_tenant_id = tid
    ctx.db.commit()


@router.post("/change-password", status_code=204)
def change_password(body: ChangePasswordIn, request: Request, ctx: AuthContext = Depends(get_auth_context)):
    if not ctx.user.password_hash:
        raise HTTPException(status_code=409, detail={"code": "no_password_set", "message": "This account signs in with Google and has no password yet. Use 'Set a password' instead."})
    if not verify_password(body.current_password, ctx.user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    ctx.user.password_hash = hash_password(body.new_password)
    _revoke_other_sessions(ctx)
    set_rls_context(ctx.db, bypass=True)
    audit(ctx.db, action="auth.password_changed", user_id=ctx.user.id, ip=client_ip(request))
    ctx.db.commit()


def _revoke_other_sessions(ctx: AuthContext) -> None:
    ctx.db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == ctx.user.id, AuthSession.id != ctx.session.id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )


@router.post("/set-password", status_code=204, dependencies=[Depends(limit_by_ip("setpw", 5, 300))])
def set_password(body: SetPasswordIn, request: Request, ctx: AuthContext = Depends(get_auth_context)):
    """First password for an account created through Google. Accounts that already have one must use change-password."""
    if ctx.user.password_hash:
        raise HTTPException(status_code=409, detail={"code": "password_already_set", "message": "This account already has a password. Use 'Change password'."})
    ctx.user.password_hash = hash_password(body.new_password)
    _revoke_other_sessions(ctx)
    set_rls_context(ctx.db, bypass=True)
    audit(ctx.db, action="auth.password_set", user_id=ctx.user.id, ip=client_ip(request))
    ctx.db.commit()


@router.post("/password-reset/request", status_code=202, dependencies=[Depends(limit_by_ip("pwreset", 5, 300))])
def password_reset_request(body: PasswordResetRequestIn, db: Session = Depends(get_db)):
    """Always answers 202 so account existence is not revealed."""
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    if user and user.is_active:
        token = new_token()
        now = utcnow()
        db.add(PasswordResetToken(
            user_id=user.id, token_hash=hash_token(token), created_at=now,
            expires_at=now + timedelta(minutes=settings.password_reset_ttl_minutes),
        ))
        db.commit()
        link = f"{settings.frontend_url}/reset-password?token={token}"
        send_email(user.email, "Reset your FlowQR password", f"Open this link to choose a new password:\n{link}")
    return {"detail": "If that email exists, a reset link has been sent."}


@router.post("/password-reset/confirm", status_code=204, dependencies=[Depends(limit_by_ip("pwreset", 10, 300))])
def password_reset_confirm(body: PasswordResetConfirmIn, db: Session = Depends(get_db)):
    row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(body.token)))
    if not row or row.used_at or row.expires_at < utcnow():
        raise HTTPException(status_code=400, detail="This reset link is invalid or has expired")
    user = db.get(User, row.user_id)
    user.password_hash = hash_password(body.new_password)
    row.used_at = utcnow()
    db.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None)).values(revoked_at=utcnow()))
    set_rls_context(db, bypass=True)
    audit(db, action="auth.password_reset", user_id=user.id, entity_type="user", entity_id=user.id)
    db.commit()


@router.post("/verify-email", status_code=204, dependencies=[Depends(limit_by_ip("verify", 20, 300))])
def verify_email(body: VerifyEmailIn, db: Session = Depends(get_db)):
    row = db.scalar(select(EmailVerificationToken).where(EmailVerificationToken.token_hash == hash_token(body.token)))
    if not row or row.used_at or row.expires_at < utcnow():
        raise HTTPException(status_code=400, detail="This verification link is invalid or has expired")
    user = db.get(User, row.user_id)
    row.used_at = utcnow()
    user.email_verified_at = user.email_verified_at or utcnow()
    # Whoever types an admin address into the sign-up form must not become an administrator: only the person who can read that mailbox does.
    if user.email in settings.platform_admin_email_set and not user.is_platform_admin:
        user.is_platform_admin = True
        # sessions opened before the grant were issued with an ordinary lifetime: bring them in line with an administrator's
        db.execute(update(AuthSession).where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None),
                                             AuthSession.expires_at > utcnow() + timedelta(hours=settings.admin_session_ttl_hours))
                   .values(expires_at=utcnow() + timedelta(hours=settings.admin_session_ttl_hours)))
        audit(db, action="auth.platform_admin_granted", user_id=user.id, entity_type="user", entity_id=user.id)
    set_rls_context(db, bypass=True)
    audit(db, action="auth.email_verified", user_id=user.id, entity_type="user", entity_id=user.id)
    db.commit()


@router.post("/resend-verification", status_code=202, dependencies=[Depends(limit_by_ip("verify", 5, 300))])
def resend_verification(ctx: AuthContext = Depends(get_auth_context)):
    if ctx.user.email_verified_at:
        return {"detail": "Already verified", "email_sent": True}
    sent = send_verification(ctx.db, ctx.user)
    ctx.db.commit()
    return {"detail": "Verification email sent" if sent else "We couldn't send the email right now. Please try again later or contact support.", "email_sent": sent}
