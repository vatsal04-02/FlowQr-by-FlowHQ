"""Google Business Profile connection (server-side OAuth, per tenant)."""
import logging
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db, set_rls_context
from app.core.deps import SESSION_COOKIE, TenantContext, ensure_verified, get_tenant_context, require_role, _load_session
from app.core.rate_limit import client_ip
from app.core.security import get_cipher, new_token, sign_state, verify_state
from app.models import (
    GoogleConnection, GoogleConnectionStatus, GoogleLocation, Location, Membership, Role, Subscription,
)
from app.models.base import utcnow
from app.models.tenancy import ROLE_RANK, User
from app.schemas.google import ConnectionOut, GoogleLocationOut, SelectionIn
from app.services import google as g
from app.services import entitlements as ent
from app.services.audit import audit
from app.services.google.queue import enqueue_sync
from app.services.google.provider import has_business_scope
from app.services.google.tokens import get_access_token, note_api_access, note_not_approved, store_tokens

log = logging.getLogger("flowqr.google")
router = APIRouter(prefix="/google", tags=["google"])
STATE_COOKIE = "flowqr_oauth_state"


def _frontend(path: str, **params) -> RedirectResponse:
    q = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(f"{settings.frontend_url.rstrip('/')}{path}{q}", status_code=303)


def _conn_out(ctx: TenantContext, c: GoogleConnection) -> ConnectionOut:
    o = ConnectionOut.model_validate(c)
    o.locations_found = ctx.db.scalar(select(func.count()).select_from(GoogleLocation).where(GoogleLocation.connection_id == c.id)) or 0
    o.no_locations = o.locations_found == 0 and c.api_access == "approved" and c.status in (GoogleConnectionStatus.pending_selection, GoogleConnectionStatus.active)
    return o


@router.get("/status")
def status(ctx: TenantContext = Depends(get_tenant_context)):
    conns = ctx.db.scalars(
        select(GoogleConnection).where(GoogleConnection.tenant_id == ctx.tenant_id, GoogleConnection.status != GoogleConnectionStatus.disconnected)
        .order_by(GoogleConnection.created_at)
    ).all()
    return {
        "configured": settings.google_configured,
        "configuration_note": None if settings.google_configured else
        "Google sign-in is not configured on this FlowQR server yet (GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET). "
        "You can keep using manual review links in the meantime.",
        "connections": [_conn_out(ctx, c) for c in conns],
    }


@router.post("/connect")
def connect(response: Response, ctx: TenantContext = Depends(require_role(Role.admin))):
    ensure_verified(ctx.user)
    ent.require_feature(ctx.db, ctx.tenant_id, "review_sync")
    if not settings.google_configured:
        raise HTTPException(status_code=503, detail={"code": "google_config_pending",
                            "message": "Google integration is awaiting configuration on the server."})
    nonce = new_token(16)
    state = sign_state(f"{nonce}|{ctx.tenant_id}|{ctx.user.id}")
    provider = g.get_google_provider()
    response.set_cookie(STATE_COOKIE, nonce, max_age=600, httponly=True, secure=settings.cookie_secure, samesite="lax", path="/")
    return {"auth_url": provider.build_auth_url(state)}


@router.get("/callback")
def callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
             oauth_nonce: str | None = Cookie(default=None, alias=STATE_COOKIE),
             session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
             db: Session = Depends(get_db)):
    def fail(reason: str):
        r = _frontend("/gbp/locations", error=reason)
        r.delete_cookie(STATE_COOKIE, path="/")
        return r

    if error:
        return fail("access_denied")
    payload = verify_state(state or "")
    if not payload or not code or not oauth_nonce:
        return fail("invalid_state")
    try:
        nonce, tenant_s, user_s = payload.split("|")
        tenant_id, user_id = uuid.UUID(tenant_s), uuid.UUID(user_s)
    except ValueError:
        return fail("invalid_state")
    if nonce != oauth_nonce:  # CSRF: state must match the browser that started the flow
        return fail("invalid_state")
    sess = _load_session(db, session_token)
    if not sess or sess.user_id != user_id:
        return fail("session_mismatch")
    set_rls_context(db, bypass=True)
    m = db.scalar(select(Membership).where(Membership.user_id == user_id, Membership.tenant_id == tenant_id))
    if not m or ROLE_RANK[m.role] < ROLE_RANK[Role.admin]:
        return fail("forbidden")
    try:
        provider = g.get_google_provider()
        ts = provider.exchange_code(code)
        info = provider.get_userinfo(ts.access_token)
    except g.GoogleNotConfigured:
        return fail("not_configured")
    except g.GoogleError as exc:
        log.warning("Google code exchange failed: %s", type(exc).__name__)
        return fail("exchange_failed")

    if not has_business_scope(ts.scope):
        # Google's consent screen lets people untick individual permissions. Without business.manage nothing here can work,
        # so refuse the connection rather than store a token that only looks connected.
        log.warning("Google connect without the business.manage scope")
        provider.revoke(ts.refresh_token or ts.access_token)
        return fail("scope_missing")
    sub = info.get("sub")
    conn = db.scalar(select(GoogleConnection).where(
        GoogleConnection.tenant_id == tenant_id, GoogleConnection.google_sub == sub,
        GoogleConnection.status != GoogleConnectionStatus.disconnected))
    if conn is None:
        if not ts.refresh_token:
            return fail("no_refresh_token")
        conn = GoogleConnection(tenant_id=tenant_id, google_sub=sub, connected_by=user_id)
        db.add(conn)
    conn.google_email = info.get("email")
    conn.scopes = ts.scope
    conn.status = GoogleConnectionStatus.pending_selection if not conn.connected_at else GoogleConnectionStatus.active
    conn.last_error, conn.connected_at = None, conn.connected_at or utcnow()
    store_tokens(conn, refresh_token=ts.refresh_token, access_token=ts.access_token, expires_in=ts.expires_in)
    db.flush()
    try:
        discover_locations(db, conn, provider, ts.access_token)
    except g.GoogleApiNotApproved as exc:
        conn.last_error = note_not_approved(conn, exc)
        conn.status = GoogleConnectionStatus.error
    except g.GoogleRateLimited as exc:
        # No Business Profile call has ever succeeded for this connection and the first one hit a quota error:
        # that is how a project with quota 0 (not approved) behaves. Say so instead of a generic failure.
        conn.last_error = note_not_approved(conn, exc)
        conn.status = GoogleConnectionStatus.error
    except g.GoogleError as exc:
        conn.last_error = f"Connected, but couldn't list Business Profile locations: {exc}"[:500]
        conn.status = GoogleConnectionStatus.error
        log.warning("Location discovery failed after connect: %s", type(exc).__name__)
    audit(db, action="google.connect", tenant_id=tenant_id, user_id=user_id, entity_type="google_connection",
          entity_id=conn.id, ip=client_ip(request))
    db.commit()
    r = _frontend("/gbp/locations", connected="1", connection=str(conn.id))
    r.delete_cookie(STATE_COOKIE, path="/")
    return r


def discover_locations(db: Session, conn: GoogleConnection, provider, access_token: str) -> int:
    count = 0
    for acct in provider.list_accounts(access_token):
        for gl in provider.list_locations(access_token, acct.name):
            row = db.scalar(select(GoogleLocation).where(
                GoogleLocation.tenant_id == conn.tenant_id, GoogleLocation.google_location_name == gl.name))
            if row is None:
                row = GoogleLocation(tenant_id=conn.tenant_id, connection_id=conn.id, google_account_name=acct.name,
                                     google_location_name=gl.name)
                db.add(row)
            row.connection_id, row.google_account_name = conn.id, acct.name
            row.title, row.address, row.place_id, row.review_url = gl.title, gl.address, gl.place_id, gl.review_url
            count += 1
    note_api_access(conn, "approved")  # real accounts/locations calls succeeded: Google has granted API access
    return count


def _conn_or_404(ctx: TenantContext, connection_id: uuid.UUID) -> GoogleConnection:
    conn = ctx.db.scalar(select(GoogleConnection).where(GoogleConnection.id == connection_id, GoogleConnection.tenant_id == ctx.tenant_id))
    if not conn:
        raise HTTPException(status_code=404, detail="Connection not found")
    return conn


@router.get("/connections/{connection_id}/locations", response_model=list[GoogleLocationOut])
def list_google_locations(connection_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    conn = _conn_or_404(ctx, connection_id)
    return ctx.db.scalars(select(GoogleLocation).where(GoogleLocation.connection_id == conn.id, ctx.scope(GoogleLocation.location_id))
                          .order_by(GoogleLocation.title)).all()


@router.post("/connections/{connection_id}/refresh-locations", response_model=list[GoogleLocationOut])
def refresh_locations(connection_id: uuid.UUID, ctx: TenantContext = Depends(require_role(Role.admin))):
    conn = _conn_or_404(ctx, connection_id)
    provider = g.get_google_provider() if settings.google_configured else None
    if not provider:
        raise HTTPException(status_code=503, detail="Google integration is awaiting configuration on the server.")
    try:
        token = get_access_token(ctx.db, conn, provider)
        discover_locations(ctx.db, conn, provider, token)
        if conn.status == GoogleConnectionStatus.error:  # recovered (e.g. Google approved the project since)
            conn.status, conn.last_error = GoogleConnectionStatus.pending_selection, None
    except (g.GoogleApiNotApproved, g.GoogleRateLimited) as exc:
        if isinstance(exc, g.GoogleRateLimited) and conn.api_access == "approved":
            raise HTTPException(status_code=429, detail="Google rate limit reached. Try again in a few minutes.")
        conn.last_error = note_not_approved(conn, exc)
        ctx.db.commit()
        raise HTTPException(status_code=409, detail={"code": "google_api_" + conn.api_access, "message": conn.last_error})
    except g.GoogleAuthRevoked:
        raise HTTPException(status_code=409, detail="Google access was revoked. Please reconnect.")
    except g.GoogleError as exc:
        raise HTTPException(status_code=502, detail=f"Google error: {exc}")
    ctx.db.commit()
    return ctx.db.scalars(select(GoogleLocation).where(GoogleLocation.connection_id == conn.id).order_by(GoogleLocation.title)).all()


@router.put("/connections/{connection_id}/selection", response_model=list[GoogleLocationOut])
def select_locations(connection_id: uuid.UUID, body: SelectionIn, request: Request,
                     ctx: TenantContext = Depends(require_role(Role.admin))):
    ent.require_feature(ctx.db, ctx.tenant_id, "review_sync")
    conn = _conn_or_404(ctx, connection_id)
    if conn.status in (GoogleConnectionStatus.revoked, GoogleConnectionStatus.disconnected):
        raise HTTPException(status_code=409, detail="This connection is not active. Reconnect Google first.")
    sub = None
    changed: list[GoogleLocation] = []
    for item in body.selections:
        gl = ctx.db.scalar(select(GoogleLocation).where(
            GoogleLocation.id == item.google_location_id, GoogleLocation.connection_id == conn.id,
            GoogleLocation.tenant_id == ctx.tenant_id))
        if not gl:
            raise HTTPException(status_code=404, detail="Google location not found")
        if item.selected:
            loc = None
            if item.location_id:
                loc = ctx.db.scalar(select(Location).where(Location.id == item.location_id, Location.tenant_id == ctx.tenant_id))
                if not loc:
                    raise HTTPException(status_code=404, detail="FlowQR location not found")
            elif item.create_location:
                e = ent.for_tenant(ctx.db, ctx.tenant_id)
                if ent.locations_used(ctx.db, ctx.tenant_id) >= e.max_locations:
                    raise HTTPException(status_code=402, detail={"code": "plan_limit", "message": f"Your plan allows up to {e.max_locations} locations."})
                loc = Location(tenant_id=ctx.tenant_id, name=gl.title or "Google location", address_line=gl.address)
                ctx.db.add(loc)
                ctx.db.flush()
            if loc is None and gl.location_id is None:
                raise HTTPException(status_code=422, detail="Map each selected Google location to a FlowQR location")
            if loc is not None:
                gl.location_id = loc.id
                if gl.review_url and not loc.review_url:  # offer Google's own review link when none set manually
                    loc.review_url, loc.review_url_source = gl.review_url, "google"
        gl.selected = item.selected
        changed.append(gl)
    if any(c.selected for c in changed):
        conn.status = GoogleConnectionStatus.active
    audit(ctx.db, action="google.select_locations", tenant_id=ctx.tenant_id, user_id=ctx.user.id,
          entity_type="google_connection", entity_id=conn.id, meta={"count": len(changed)}, ip=client_ip(request))
    ctx.db.commit()
    enqueue_sync(ctx.db, [c.id for c in changed if c.selected])
    return ctx.db.scalars(select(GoogleLocation).where(GoogleLocation.connection_id == conn.id).order_by(GoogleLocation.title)).all()


@router.post("/sync")
def sync_now(ctx: TenantContext = Depends(require_role(Role.admin))):
    ent.require_feature(ctx.db, ctx.tenant_id, "review_sync")
    ids = ctx.db.scalars(
        select(GoogleLocation.id).join(GoogleConnection, GoogleConnection.id == GoogleLocation.connection_id).where(
            GoogleLocation.tenant_id == ctx.tenant_id, GoogleLocation.selected.is_(True),
            GoogleConnection.status == GoogleConnectionStatus.active)
    ).all()
    if not ids:
        raise HTTPException(status_code=409, detail="No connected Google locations to sync")
    return {"result": enqueue_sync(ctx.db, list(ids)), "locations": len(ids)}


@router.delete("/connections/{connection_id}", status_code=204)
def disconnect(connection_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    conn = _conn_or_404(ctx, connection_id)
    if conn.refresh_token_encrypted:
        try:
            token = get_cipher().decrypt(conn.refresh_token_encrypted)
            if settings.google_configured:
                g.get_google_provider().revoke(token)  # best-effort revoke at Google
        except Exception:
            log.warning("Token revoke at Google failed (continuing with local disconnect)")
    conn.refresh_token_encrypted = None
    conn.access_token_encrypted = None
    conn.access_token_expires_at = None
    conn.status = GoogleConnectionStatus.disconnected
    conn.disconnected_at = utcnow()
    for gl in ctx.db.scalars(select(GoogleLocation).where(GoogleLocation.connection_id == conn.id)):
        gl.selected = False  # stop syncing; synced reviews are kept as history
    audit(ctx.db, action="google.disconnect", tenant_id=ctx.tenant_id, user_id=ctx.user.id,
          entity_type="google_connection", entity_id=conn.id, ip=client_ip(request))
    ctx.db.commit()
