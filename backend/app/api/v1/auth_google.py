"""Continue with Google (sign in / sign up / link). Server-side OIDC code flow with state + nonce + PKCE(S256).

The three one-time values live only in a short-lived, signed, HttpOnly cookie scoped to this router's path, so the
callback can only complete in the browser that started the flow. Google tokens are never stored.

Account rules (all enforced in `callback`):
  * identity is Google's `sub`; an email is only ever used when Google says `email_verified=true`
  * a returning `sub` logs in (no email involved)
  * a new `sub` whose email matches an existing account links ONLY if that account's email is already verified;
    an unverified existing account is refused (otherwise someone who pre-registered a victim's address with a
    password they control would keep access after the victim signs in with Google)
  * a signed-in user can link Google to their own account via POST /link (CSRF-protected, never a bare GET)
"""
import logging
import time
from dataclasses import dataclass
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.auth import _start_session
from app.core.config import settings
from app.core.db import get_db, set_rls_context
from app.core.deps import SESSION_COOKIE, AuthContext, _load_session, get_auth_context
from app.core.rate_limit import client_ip, limit_by_ip
from app.core.security import constant_time_equals, new_token, sign_state, verify_state
from app.models import User
from app.models.base import utcnow
from app.services.audit import audit
from app.services.google.login import GoogleLoginError, get_google_login_provider, pkce_challenge

log = logging.getLogger("flowqr.auth.google")
router = APIRouter(prefix="/auth/google", tags=["auth"])

FLOW_COOKIE = "flowqr_gl_oauth"
FLOW_COOKIE_PATH = "/api/v1/auth/google"
FLOW_TTL_SECONDS = 600
LOGIN, LINK = "login", "link"


@dataclass
class _Flow:
    state: str
    nonce: str
    verifier: str
    intent: str
    user_id: str


def _flow_cookie(response: Response, flow: _Flow) -> None:
    payload = "|".join([flow.state, flow.nonce, flow.verifier, flow.intent, flow.user_id or "-", str(int(time.time()))])
    response.set_cookie(FLOW_COOKIE, sign_state(payload), max_age=FLOW_TTL_SECONDS, httponly=True,
                        secure=settings.cookie_secure, samesite="lax", path=FLOW_COOKIE_PATH)


def _read_flow(raw: str | None) -> _Flow | None:
    payload = verify_state(raw or "")
    if not payload:
        return None
    parts = payload.split("|")
    if len(parts) != 6:
        return None
    state, nonce, verifier, intent, user_id, issued = parts
    try:
        if time.time() - int(issued) > FLOW_TTL_SECONDS:
            return None
    except ValueError:
        return None
    if intent not in (LOGIN, LINK):
        return None
    return _Flow(state, nonce, verifier, intent, "" if user_id == "-" else user_id)


def _new_flow(intent: str, user_id: str = "") -> _Flow:
    return _Flow(state=new_token(24), nonce=new_token(24), verifier=new_token(48), intent=intent, user_id=user_id)


def _auth_url(flow: _Flow) -> str:
    return get_google_login_provider().build_auth_url(flow.state, flow.nonce, pkce_challenge(flow.verifier))


def _redirect(path: str, **params) -> RedirectResponse:
    q = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(f"{settings.frontend_url.rstrip('/')}{path}{q}", status_code=303)


def _done(r: RedirectResponse) -> RedirectResponse:
    r.delete_cookie(FLOW_COOKIE, path=FLOW_COOKIE_PATH)  # the flow is single-use whatever the outcome
    return r


def _not_configured() -> HTTPException:
    return HTTPException(status_code=503, detail={"code": "google_login_not_configured",
                                                  "message": "Google sign-in isn't available on this server yet."})


@router.get("/start", dependencies=[Depends(limit_by_ip("gl-start", 20, 60))])
def start():
    """Full-page redirect target for the "Continue with Google" button."""
    if not settings.google_login_configured:
        return _redirect("/login", google_error="not_configured")
    flow = _new_flow(LOGIN)
    r = RedirectResponse(_auth_url(flow), status_code=303)
    _flow_cookie(r, flow)
    return r


@router.post("/link")
def link(response: Response, ctx: AuthContext = Depends(get_auth_context)):
    """Signed-in user wants to attach a Google account. POST + CSRF header, so a third-party page cannot start it."""
    if not settings.google_login_configured:
        raise _not_configured()
    flow = _new_flow(LINK, str(ctx.user.id))
    _flow_cookie(response, flow)
    return {"auth_url": _auth_url(flow)}


@router.get("/callback", dependencies=[Depends(limit_by_ip("gl-callback", 30, 60))])
def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
             flow_cookie: str | None = Cookie(default=None, alias=FLOW_COOKIE),
             session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
             db: Session = Depends(get_db)):
    flow = _read_flow(flow_cookie)
    intent = flow.intent if flow else LOGIN

    def fail(reason: str) -> RedirectResponse:
        return _done(_redirect("/settings/account" if intent == LINK else "/login", google_error=reason))

    if error:
        return fail("access_denied")
    # state: must be the exact value this browser was given (CSRF / login-CSRF defence)
    if not flow or not code or not state or not constant_time_equals(state, flow.state):
        return fail("invalid_state")
    if not settings.google_login_configured:
        return fail("not_configured")

    try:
        identity = get_google_login_provider().exchange_and_verify(code, flow.verifier, flow.nonce)
    except GoogleLoginError as exc:
        log.warning("Google sign-in rejected: %s", exc.code)
        return fail(exc.code if exc.code in ("invalid_nonce", "invalid_token") else "exchange_failed")

    set_rls_context(db, bypass=True)
    try:
        if flow.intent == LINK:
            return _link_existing(db, request, session_token, flow, identity, fail)
        return _sign_in(db, request, identity, fail)
    except IntegrityError:  # two callbacks racing to create/link the same account
        db.rollback()
        return fail("exchange_failed")


def _link_existing(db: Session, request: Request, session_token, flow: _Flow, identity, fail) -> RedirectResponse:
    sess = _load_session(db, session_token)
    if not sess or str(sess.user_id) != flow.user_id:
        return fail("session_mismatch")
    user = db.get(User, sess.user_id)
    if not user or not user.is_active:
        return fail("account_disabled")
    if not identity.email_verified:
        return fail("email_not_verified")
    owner = db.scalar(select(User).where(User.google_sub == identity.sub))
    if (owner and owner.id != user.id) or (user.google_sub and user.google_sub != identity.sub):
        return fail("already_linked")
    user.google_sub = identity.sub
    audit(db, action="auth.google_linked", user_id=user.id, entity_type="user", entity_id=user.id, ip=client_ip(request))
    db.commit()
    return _done(_redirect("/settings/account", google="linked"))


def _sign_in(db: Session, request: Request, identity, fail) -> RedirectResponse:
    user = db.scalar(select(User).where(User.google_sub == identity.sub))
    created = False
    if user is None:
        # A new Google identity: the email is the only thing that can connect it to an account, so Google must vouch for it.
        if not identity.email or not identity.email_verified:
            return fail("email_not_verified")
        user = db.scalar(select(User).where(User.email == identity.email))
        if user is not None:
            if not user.email_verified_at:
                return fail("account_unverified")
            if user.google_sub:  # a different Google account is already linked to this email's user
                return fail("already_linked")
            if not user.is_active:
                return fail("account_disabled")
            user.google_sub = identity.sub
            audit(db, action="auth.google_linked", user_id=user.id, entity_type="user", entity_id=user.id,
                  ip=client_ip(request), meta={"via": "verified_email"})
        else:
            user = User(
                email=identity.email, password_hash=None, google_sub=identity.sub,
                full_name=((identity.name or "").strip() or identity.email.split("@")[0])[:200],
                email_verified_at=utcnow(), is_platform_admin=identity.email in settings.platform_admin_email_set,
            )
            db.add(user)
            db.flush()
            created = True
            audit(db, action="auth.register", user_id=user.id, entity_type="user", entity_id=user.id,
                  ip=client_ip(request), meta={"via": "google"})
    elif not user.is_active:
        return fail("account_disabled")

    user.last_login_at = utcnow()
    response = _redirect("/onboarding" if created else "/overview")
    _start_session(db, user, request, response)
    audit(db, action="auth.login", user_id=user.id, entity_type="user", entity_id=user.id, ip=client_ip(request),
          meta={"via": "google"})
    db.commit()
    return _done(response)
