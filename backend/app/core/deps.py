"""Authentication, CSRF and tenant-scoping dependencies.

Every tenant-scoped endpoint depends on `TenantCtx` (or `require_role(...)`). The tenant is
derived from the server-side session + membership check — NEVER from request bodies/params.
"""
import uuid
from dataclasses import dataclass

from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy import select, true
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db, set_rls_context
from app.core.security import constant_time_equals, hash_token
from app.models import AuthSession, Membership, MembershipLocation, Role, Tenant, User
from app.models.base import utcnow
from app.models.tenancy import ROLE_RANK

SESSION_COOKIE = "flowqr_session"
CSRF_COOKIE = "flowqr_csrf"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass
class AuthContext:
    db: Session
    user: User
    session: AuthSession


@dataclass
class TenantContext:
    db: Session
    user: User
    session: AuthSession
    tenant: Tenant
    membership: Membership
    # Location-level permission: None = every location (owners, admins, unrestricted staff); otherwise the ONLY locations
    # this member may see. Resolved server-side from the membership on every request, never from the client.
    location_ids: frozenset[uuid.UUID] | None = None

    @property
    def tenant_id(self) -> uuid.UUID:
        return self.tenant.id

    @property
    def restricted(self) -> bool:
        return self.location_ids is not None

    def can_access_location(self, location_id: uuid.UUID | None) -> bool:
        """Data that is not tied to a location (location_id NULL) is denied to restricted members: deny by default."""
        return self.location_ids is None or (location_id is not None and location_id in self.location_ids)

    def require_location(self, location_id: uuid.UUID | None, what: str = "Location") -> None:
        if not self.can_access_location(location_id):
            raise HTTPException(status_code=404, detail=f"{what} not found")  # 404, not 403: don't confirm it exists

    def scope(self, column):
        """SQL condition limiting `column` (a location id) to what this member may see. Use it on every list/aggregate query."""
        return true() if self.location_ids is None else column.in_(list(self.location_ids))

    @property
    def role(self) -> Role:
        return self.membership.role


def _load_session(db: Session, token: str | None) -> AuthSession | None:
    if not token:
        return None
    # auth_sessions is not tenant scoped; no RLS context needed.
    sess = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if not sess or sess.revoked_at is not None or sess.expires_at < utcnow():
        return None
    return sess


def location_scope(db: Session, membership: Membership) -> frozenset[uuid.UUID] | None:
    """The locations a membership is limited to, or None for all. Needs the tenant RLS context (or bypass) to be set."""
    if ROLE_RANK[membership.role] >= ROLE_RANK[Role.admin] or membership.all_locations:
        return None
    return frozenset(db.scalars(select(MembershipLocation.location_id).where(MembershipLocation.membership_id == membership.id)))


def member_may_act(db: Session, tenant_id: uuid.UUID, user_id: uuid.UUID | None, location_id: uuid.UUID | None, minimum: Role) -> bool:
    """For background jobs that act on a person's earlier decision: is that person STILL allowed to do it?
    (still a member, still at least `minimum`, still has the location). Caller must be in a bypass/system session."""
    if not user_id:
        return False
    m = db.scalar(select(Membership).where(Membership.tenant_id == tenant_id, Membership.user_id == user_id))
    if not m or ROLE_RANK[m.role] < ROLE_RANK[minimum]:
        return False
    user = db.get(User, user_id)
    if not user or not user.is_active:
        return False
    ids = location_scope(db, m)
    return ids is None or (location_id is not None and location_id in ids)


def get_auth_context(
    request: Request,
    db: Session = Depends(get_db),
    session_token: str | None = Cookie(default=None, alias=SESSION_COOKIE),
    x_csrf_token: str | None = Header(default=None),
) -> AuthContext:
    sess = _load_session(db, session_token)
    if not sess:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if request.method in UNSAFE_METHODS:
        # CSRF: header must match the token bound to the server-side session.
        if not x_csrf_token or not constant_time_equals(x_csrf_token, sess.csrf_token):
            raise HTTPException(status_code=403, detail="Invalid CSRF token")
    user = db.get(User, sess.user_id)
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return AuthContext(db=db, user=user, session=sess)


def get_tenant_context(
    auth: AuthContext = Depends(get_auth_context),
    x_tenant_id: str | None = Header(default=None),
) -> TenantContext:
    """Resolve the active tenant from the session's memberships.

    `X-Tenant-Id` is only a *selector* among tenants the user is a member of; membership is
    always verified server-side.
    """
    db = auth.db
    # Memberships are RLS-protected: read them under bypass, then narrow to the chosen tenant.
    set_rls_context(db, bypass=True)
    memberships = list(db.scalars(select(Membership).where(Membership.user_id == auth.user.id)))
    chosen: Membership | None = None
    wanted = None
    if x_tenant_id:
        try:
            wanted = uuid.UUID(x_tenant_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid tenant")
    elif auth.session.active_tenant_id:
        wanted = auth.session.active_tenant_id
    for m in memberships:
        if wanted and m.tenant_id == wanted:
            chosen = m
    if chosen is None and not wanted and memberships:
        chosen = memberships[0]
    if chosen is None:
        set_rls_context(db)  # drop elevated context
        raise HTTPException(status_code=403, detail="No access to this business")
    tenant = db.get(Tenant, chosen.tenant_id)
    if not tenant or not tenant.is_active:
        set_rls_context(db)
        raise HTTPException(status_code=403, detail={"code": "account_suspended", "message": "This business account is suspended. Contact FlowQR support."})
    set_rls_context(db, tenant_id=tenant.id)  # from here on, RLS confines the session to this tenant
    return TenantContext(db=db, user=auth.user, session=auth.session, tenant=tenant, membership=chosen, location_ids=location_scope(db, chosen))


def require_role(minimum: Role):
    def dependency(ctx: TenantContext = Depends(get_tenant_context)) -> TenantContext:
        if ROLE_RANK[ctx.role] < ROLE_RANK[minimum]:
            raise HTTPException(status_code=403, detail="You do not have permission to do this")
        return ctx

    return dependency


def require_platform_admin(auth: AuthContext = Depends(get_auth_context)) -> AuthContext:
    if not auth.user.is_platform_admin:
        raise HTTPException(status_code=403, detail="Platform admin only")
    set_rls_context(auth.db, bypass=True)
    return auth


def public_db(db: Session = Depends(get_db)) -> Session:
    """Session for unauthenticated public endpoints (card resolution). Bypass is applied only
    to the narrow queries those handlers perform."""
    set_rls_context(db, bypass=True)
    return db


def ensure_verified(user: User) -> None:
    """Sensitive actions (billing, inviting staff, connecting Google) need a verified email."""
    if settings.require_verified_email and not user.email_verified_at:
        raise HTTPException(status_code=403, detail={"code": "email_not_verified", "message": "Please verify your email address first."})
