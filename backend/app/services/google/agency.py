"""Agency manager account: FlowQR acts on a client's Business Profile as a MANAGER the client invited, instead of holding the client's own OAuth token
(docs/audits/GOOGLE_CLIENT_ACCOUNT_OPTIONS.md, Option B).

The flow, one client location at a time, each step durable and safe to repeat (every step commits before the next and checks what Google already holds):

    consented  the client agreed, in the app, to this exact text (version and hash stored). NOTHING is sent to Google before this.
    invited    FlowQR invited its agency login as MANAGER, using the CLIENT's token. A duplicate is detected by listing the admins first (and by Google's own refusal).
    accepted   the agency login accepted the invitation with ITS OWN token. The separate notice to the client is due within GOOGLE_AGENCY_NOTICE_HOURS from here.
    verified   the agency login can LIST the location. Until this is true nothing else changes.
    active     the connection switched to `agency_account` mode (every selected location of the connection verified), then the client's token was revoked at Google.

    needs_attention  a step cannot finish without a person (not visible after the wait, refusal). Never retried automatically, so there is no retry loop.
    stopping / stopped   the client pressed "Stop FlowQR managing my profile": all work stops at once, FlowQR removes itself within GOOGLE_AGENCY_REMOVAL_BUSINESS_DAYS.
    lost       the client removed FlowQR in Google. Detected on a permission error or by the periodic check; all work for that client stops and a person is told.
    failed / cancelled   ended before the invite, or the client withdrew. The client's token was never touched.

WHAT is invited (docs/audits/GOOGLE_CLIENT_ACCOUNT_OPTIONS.md section 11). Each authorization records its own target, and the two are never mixed in one request:
    FLOWHQ_LOCATION_GROUP   (the intended architecture) the client invites FlowQR's Business Group (LocationGroup, `accounts/<id>`) in Admin.account; no e-mail is sent. Access follows membership of
                            that group, so the agency Google USER that accepts and operates must belong to it. Verified by the location being listed UNDER THE GROUP.
    INDIVIDUAL_AGENCY_USER  (documented fallback, only if GOOGLE_AGENCY_INDIVIDUAL_FALLBACK=true and no group-capable agency login exists) one person's e-mail in Admin.admin.
Kept apart on every record: the invitation target (target_type, target_account_name), the agency Google user (agency_account_id), the account the invitation was found under
(receiving_account_name), the accepted manager resource (admin_resource_name) and the verified location access (agency_account_name, verified_at).

The documented sequence for a Location Group (transfer-locations, "Transferring to a location group", and manage-locations) and who does what in this code:
    merchant credentials  locations.admins.create with `account` = the group                      (_step_invite; the duplicate guard reads the admin list, withdrawal and the final revoke use it too)
    group administrator   accounts.invitations.list with the GROUP as parent, then ...:accept      (_step_accept, with the agency Google user's token)
    group credentials     accounts.locations.list on the group: the location must appear           (_step_verify, and the periodic check)
    BEFORE any of it      accounts.list with the agency user's token must show the group typed LOCATION_GROUP (_group_preflight): the user is an administrator, and the id is not the organisation's.
Nothing here ever transfers ownership (no locations.transfer, never an Owner role), and the organisation id is never used in place of the group id.

Hard rules kept here: the role is MANAGER only; any failure before the switch leaves the connection and the client's token exactly as they were; the agency logins' tokens use their own key;
no token, e-mail body or Google content is ever logged; and the flow stores no Google content at all (only the dates and names of its own control record).

TODO(verify) items (what Google's reference does not say) are collected in docs/audits/GOOGLE_CLIENT_ACCOUNT_OPTIONS.md section 8 and marked at each place they matter.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import system_session
from app.core.rate_limit import hit
from app.core.security import TokenCipher, get_cipher
from app.models import (
    AuditLog, GoogleAgencyAccount, GoogleAgencyAuthorization, GoogleConnection, GoogleConnectionStatus, GoogleLocation,
)
from app.models.base import utcnow
from app.services import google as g
from app.services.audit import audit
from app.services.google import agency_audit  # noqa: F401  (registers the listener that audits EVERY authorization status change)
from app.services.google import agency_client as ac
from app.services.google.agency_client import InviteTarget, location_key
from app.services.google.provider import has_business_scope

log = logging.getLogger("flowqr.google.agency")
Auth = GoogleAgencyAuthorization

WORKING = ("consented", "invited", "accepted", "verified")
LIVE = WORKING + ("active", "needs_attention", "stopping")  # the states that hold the "one open authorization per location" slot
GROUP, INDIVIDUAL = InviteTarget.FLOWHQ_LOCATION_GROUP.value, InviteTarget.INDIVIDUAL_AGENCY_USER.value
CONSENT_VERSION = "agency-manager-2026-11-21-b"
_CONSENT = """FlowQR would like to join your Google Business Profile as a Manager.

What this means:
- FlowQR's own manager account is invited to this location. It is a FlowQR business account that only FlowQR staff can use, and you do not have to do anything in Google.
- The role is Manager, never Owner. FlowQR cannot remove you or change who owns the profile.
- FlowQR then reads your reviews and, only with your approval, replies, posts and updates your profile. Anything public still needs your approval, unless you separately switched on a specific automatic reply.
- {revoke}
- We email you a separate notice when FlowQR becomes a manager.
- You can stop at any time: press "Stop FlowQR managing my profile" in FlowQR, or remove FlowQR in Google (Business Profile, People and access). FlowQR stops work at once and removes itself within {days} business days of your request."""

_REVOKE_NOW = "Once FlowQR has joined and checked that it can see your profile, FlowQR signs out of the Google login you just used and revokes it, so it no longer holds your Google login."
_REVOKE_LATER = ("Once FlowQR has joined and checked that it can see your profile, FlowQR stops using the Google login you just used. It keeps that login, unused and encrypted, for up to {hours} hours "
                 "in case the switch has to be undone, and then revokes it.")


def consent_text() -> str:
    """The wording the client agrees to. It says what really happens to their Google login: revoked at once (the default), or kept unused for GOOGLE_AGENCY_CLIENT_TOKEN_KEEP_HOURS first."""
    keep = settings.google_agency_client_token_keep_hours
    return _CONSENT.format(days=settings.google_agency_removal_business_days, revoke=_REVOKE_LATER.format(hours=keep) if keep > 0 else _REVOKE_NOW)


def consent_sha() -> str:
    return hashlib.sha256(consent_text().encode()).hexdigest()


class AgencyError(Exception):
    code = "agency_error"

    def __init__(self, message: str = ""):
        super().__init__(message or self.code)


class AgencyDisabled(AgencyError):
    code = "agency_disabled"


class ConsentRequired(AgencyError):
    code = "consent_required"


class NoAgencyAccount(AgencyError):
    code = "no_agency_account"


class ScopeInvalid(AgencyError):
    code = "scope_invalid"


class ReplayDetected(AgencyError):
    code = "replay_detected"


class LocationAlreadyManaged(AgencyError):
    code = "location_already_managed"


def enabled() -> bool:
    return bool(settings.google_agency_manager_enabled)


def operations_enabled() -> bool:
    """May an agency-managed connection ACT (sync, replies, posts, edits), and may onboarding switch to the agency login and revoke the client's token? Off by default and, in production, refused
    without GOOGLE_AGENCY_POLICY_REFERENCE: Google's published restriction on shared-project, multi-business access is not resolved by an invitation being accepted."""
    if not (enabled() and settings.google_agency_operations_enabled):
        return False
    if settings.is_production and (not settings.google_agency_policy_reference.strip() or settings.google_agency_project_model != "flowhq_own_project"):
        return False  # defence in depth: the start-up guard refuses this combination, and the run-time answer is no as well. No project model decided = no agency token is used
    return True


def add_business_days(start: datetime, n: int) -> datetime:
    """Monday to Friday. Public holidays are NOT excluded, so the real deadline can only be later than this one for the client and never earlier."""
    d, added = start, 0
    while added < n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            added += 1
    return d


# ------------------------------------------------------------------ agency accounts (platform-only table, own session, own key)
@contextmanager
def _platform():
    s = system_session()
    try:
        yield s
    finally:
        s.close()


def _agency_cipher() -> TokenCipher:
    if not settings.agency_token_encryption_key:
        raise g.GoogleAgencyUnavailable("AGENCY_TOKEN_ENCRYPTION_KEY is not configured")
    return TokenCipher(settings.agency_token_encryption_key)


def alert_internal(subject: str, lines: list[str]) -> None:
    """Tell the FlowQR administrators. Never raises; never carries a token."""
    try:
        from app.core import monitoring
        from app.services.mailer import send_email

        body = "FlowQR agency manager account:\n\n" + "\n".join(f"- {x}" for x in lines) + f"\n\nOpen {settings.frontend_url}/admin/ops"
        for to in sorted(settings.platform_admin_email_set):
            send_email(to, f"[FlowQR] {subject}"[:150], body)
        monitoring.capture_message(f"agency: {subject}", "error")
    except Exception as exc:  # noqa: BLE001 - an alert problem must not break the flow it reports on
        log.warning("agency alert failed: %s", type(exc).__name__)


def refuse_if_organisation(group: str | None) -> None:
    """The Organisation ID is not the Location Group ID. If the organisation is configured and the group equals it, stop: the request would target the wrong kind of account."""
    org = (settings.google_agency_organization_id or "").strip()
    if org and group:
        try:
            same = ac.normalize_group(org) == group
        except ValueError:
            same = False
        if same:
            raise AgencyError(f"{group} is FlowQR's organisation, not its Location Group")


_STATE_TTL_SECONDS = 15 * 60  # a person signs in and copies the code within minutes; a state older than this is refused


def _state_key() -> bytes:
    """A MAC key derived (domain-separated) from the agency key: the state is signed with something only this installation holds, and the signing key is not the encryption key itself."""
    key = settings.agency_token_encryption_key
    if not key:
        raise AgencyError("AGENCY_TOKEN_ENCRYPTION_KEY is not set")
    return hashlib.sha256(b"flowqr-agency-oauth-state-v1|" + key.encode()).digest()


def new_oauth_state(now: datetime | None = None) -> str:
    """A cryptographically random, signed, short-lived OAuth `state` for registering the agency login: `<random>.<expiry>.<signature>`. It stores nothing, so it works from any shell,
    and it can be used ONCE (consume_oauth_state records the use). The random part comes from `secrets` (256 bits)."""
    payload = f"{secrets.token_urlsafe(32)}.{int((now or utcnow()).timestamp()) + _STATE_TTL_SECONDS}"
    return f"{payload}.{hmac.new(_state_key(), payload.encode(), hashlib.sha256).hexdigest()}"


def consume_oauth_state(state: str, *, now: datetime | None = None) -> None:
    """Accept a state exactly once. Refused (and nothing recorded) when it is malformed, was signed by another installation, has expired, or was already used. The use is recorded in the audit log
    BEFORE the single-use Google code is spent, so a replay can never succeed, even if the exchange then fails. Nothing secret is stored: only a hash of the random part."""
    parts = (state or "").split(".")
    if len(parts) != 3 or not all(parts):
        raise AgencyError("The sign-in state is missing or malformed. Start again with google-agency-auth-url.")
    nonce, expiry, signature = parts
    expected = hmac.new(_state_key(), f"{nonce}.{expiry}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise AgencyError("The sign-in state was not issued by this installation. Start again with google-agency-auth-url.")
    try:
        expires = int(expiry)
    except ValueError:
        raise AgencyError("The sign-in state is malformed. Start again with google-agency-auth-url.")
    if expires < int((now or utcnow()).timestamp()):
        raise AgencyError("The sign-in state has expired. Start again with google-agency-auth-url.")
    digest = hashlib.sha256(nonce.encode()).hexdigest()
    with _platform() as s:
        if s.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "google.agency.oauth_state_used", AuditLog.entity_id == digest)):
            raise AgencyError("This sign-in state was already used. Start again with google-agency-auth-url.")
        audit(s, action="google.agency.oauth_state_used", entity_type="agency_oauth_state", entity_id=digest)
        s.commit()


def agency_auth_url(provider, state: str) -> str:
    """The Google sign-in address for the AGENCY login. It asks for `openid email` (to read WHO signed in) and the Business Profile scope only, offline access for the refresh token, and it
    switches `include_granted_scopes` OFF so nothing this Google account granted earlier is folded in. (The customer sign-in is not changed.)"""
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

    parts = urlsplit(provider.build_auth_url(state))
    query = [(k, "false" if k == "include_granted_scopes" else v) for k, v in parse_qsl(parts.query)]
    return urlunsplit(parts._replace(query=urlencode(query)))


def register_account(label: str, *, code: str, max_locations: int | None = None, provider=None, location_group_id: str | None = None, expected_email: str | None = None, state: str | None = None) -> uuid.UUID:
    """Store an agency Google login from an authorization code a PERSON obtained with the agency account (python -m app.cli google-agency-register).
    The refresh token is encrypted with the agency key and never printed. `location_group_id` (default GOOGLE_AGENCY_LOCATION_GROUP_ID) is the FlowQR LocationGroup this
    Google USER belongs to: clients invite the group, and this user accepts and operates on its behalf. Without one the login can only be used for the individual fallback.

    `expected_email` is WHO the person says they signed in as. The identity that counts is the one GOOGLE returns for the token (userinfo), never the label or this claim: if they differ,
    the grant just issued is revoked at Google and NOTHING is stored (a wrong Google account, e.g. a client's or a personal one, must never become the agency login)."""
    wanted = location_group_id or settings.google_agency_location_group_id
    try:  # checked BEFORE the single-use code is spent
        group = ac.normalize_group(wanted) if wanted else None
    except ValueError as exc:
        raise AgencyError(str(exc))
    refuse_if_organisation(group)
    if state is not None:
        consume_oauth_state(state)  # random, signed, unexpired and unused, or nothing happens: the single-use Google code is not spent
    provider = provider or g.get_google_provider()
    ts = provider.exchange_code(code)
    if not has_business_scope(ts.scope):
        provider.revoke(ts.refresh_token or ts.access_token)
        raise AgencyError("The agency login did not grant the Business Profile scope")
    if not ts.refresh_token:
        raise AgencyError("Google returned no refresh token for the agency login")
    info = provider.get_userinfo(ts.access_token)
    email = (info.get("email") or "").strip().lower()
    if not email:
        raise AgencyError("Google returned no e-mail for the agency login")
    if expected_email and email != expected_email.strip().lower():
        provider.revoke(ts.refresh_token or ts.access_token)  # do not keep a grant for the wrong Google account
        raise AgencyError("The Google account that signed in is not the expected agency account. Nothing was stored and the sign-in was revoked.")
    cipher = _agency_cipher()
    with _platform() as s:
        row = s.scalar(select(GoogleAgencyAccount).where(GoogleAgencyAccount.google_email == email))
        if row is None:
            row = GoogleAgencyAccount(label=label, google_email=email)
            s.add(row)
        row.google_sub, row.status, row.last_error = info.get("sub"), "active", None
        row.max_locations = max_locations if max_locations else row.max_locations
        row.location_group_name = group or row.location_group_name
        row.refresh_token_encrypted = cipher.encrypt(ts.refresh_token)
        row.access_token_encrypted = cipher.encrypt(ts.access_token)
        row.access_token_expires_at = utcnow() + timedelta(seconds=ts.expires_in)
        s.commit()
        return row.id


def agency_access_token(account_id: uuid.UUID, provider=None) -> str:
    """A valid access token for an agency login, refreshed when needed. Uses its OWN session (the table is platform-only) so it works from a request and from a worker alike."""
    cipher = _agency_cipher()
    with _platform() as s:
        row = s.get(GoogleAgencyAccount, account_id)
        if row is None or row.status != "active" or not row.refresh_token_encrypted:
            raise g.GoogleAgencyUnavailable("The agency account is not active")
        if row.access_token_encrypted and row.access_token_expires_at and row.access_token_expires_at > utcnow() + timedelta(seconds=60):
            return cipher.decrypt(row.access_token_encrypted)
        provider = provider or g.get_google_provider()
        try:
            ts = provider.refresh_access_token(cipher.decrypt(row.refresh_token_encrypted))
        except g.GoogleAuthRevoked:
            row.status, row.last_error, row.access_token_encrypted = "revoked", "Google access for this agency login was revoked", None
            s.commit()
            alert_internal("agency login revoked", [f"Agency account '{row.label}' can no longer sign in to Google. Every client on it is paused until it is re-registered."])
            raise g.GoogleAgencyUnavailable("The agency login was revoked")
        row.access_token_encrypted = cipher.encrypt(ts.access_token)
        row.access_token_expires_at = utcnow() + timedelta(seconds=ts.expires_in)
        if ts.refresh_token:
            row.refresh_token_encrypted = cipher.encrypt(ts.refresh_token)
        s.commit()
        return ts.access_token


class AgencyResolutionError(g.GoogleAgencyUnavailable):
    """The agency connection could not be resolved to ONE explicit, active, authorized mapping, so nothing is sent to Google. Handled like any unavailable agency login by every caller (the client's
    stored connection is NOT changed), but it carries a stable `code` so the cause is visible: it never silently falls back to another tenant, account or location."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AgencyAccess:
    """What a resolved agency connection may use: ids only, never a token."""
    tenant_id: uuid.UUID
    connection_id: uuid.UUID
    agency_account_id: uuid.UUID
    group_name: str | None
    authorization_ids: tuple[uuid.UUID, ...]
    location_resource: str | None


def _deny(conn: GoogleConnection, code: str, message: str, gloc: GoogleLocation | None = None) -> AgencyResolutionError:
    """Record WHY a resolution was refused (no token, e-mail, review text or Google content) in a session of its own, so a refusal is kept even if the caller rolls back, and return the error to raise."""
    try:
        with _platform() as s:
            audit(s, action="google.agency.resolution_denied", tenant_id=conn.tenant_id, entity_type="google_connection", entity_id=conn.id,
                  meta={"code": code, "location": location_resource(gloc) if gloc is not None else None})
            s.commit()
    except Exception:  # noqa: BLE001 - the audit write must never turn a refusal into a different failure
        log.warning("could not record an agency resolution refusal (%s)", code)
    return AgencyResolutionError(code, message)


def resolve_agency_access(db: Session, conn: GoogleConnection, gloc: GoogleLocation | None = None) -> AgencyAccess:
    """Resolve an agency_account connection to its explicit authorization(s), or refuse with a specific code. Called for EVERY use of the agency login (see tokens.get_access_token).

    With a location (`gloc`) the mapping must be exactly one ACTIVE authorization for that tenant, connection, agency login and Google location, the location must sit under the group the authorization
    targets, and no other business may hold an open authorization for the same Google location. Without one (a connection-level call) at least one active authorization of this connection must exist and
    every one of them must belong to this tenant and this agency login. There is no fallback: a missing or ambiguous mapping is a refusal, never another tenant's, account's or location's token.
    This reads the database only. It does not ask Google (the group membership was verified when the authorization became active, and the periodic verification repeats it)."""
    if conn.auth_mode != "agency_account":
        raise _deny(conn, "not_agency_connection", "This connection does not run on the agency login", gloc)
    if not enabled():
        raise g.GoogleAgencyUnavailable("Agency management is switched off")
    if not operations_enabled():
        raise g.GoogleAgencyUnavailable("Agency operations are switched off")  # verified access is not permission to run: nothing is sent to Google on this connection's behalf
    if not conn.agency_account_id:
        raise _deny(conn, "no_agency_account", "No agency account is recorded for this connection", gloc)
    if gloc is not None and (gloc.connection_id != conn.id or gloc.tenant_id != conn.tenant_id):
        raise _deny(conn, "tenant_mismatch", "That location does not belong to this connection", gloc)
    with _platform() as s:
        row = s.get(GoogleAgencyAccount, conn.agency_account_id)
        group = row.location_group_name if row is not None else None
        row_ok = row is not None and row.status == "active"
        others = 0
        if gloc is not None:
            others = s.scalar(select(func.count()).select_from(Auth).where(
                Auth.google_location_resource == location_resource(gloc), Auth.tenant_id != conn.tenant_id, Auth.status.in_(LIVE))) or 0
    if not row_ok:
        raise _deny(conn, "agency_account_inactive", "The agency account is not active", gloc)
    q = select(Auth).where(Auth.connection_id == conn.id, Auth.status == "active")
    if gloc is not None:
        q = q.where(Auth.google_location_id == gloc.id)
    auths = list(db.scalars(q))
    if not auths:
        raise _deny(conn, "no_mapping", "No active authorization maps this location to the agency login" if gloc is not None else "No active authorization exists for this connection", gloc)
    if gloc is not None and len(auths) > 1:
        raise _deny(conn, "duplicate_mapping", "More than one active authorization exists for this location", gloc)
    if any(a.tenant_id != conn.tenant_id or a.agency_account_id != conn.agency_account_id for a in auths):
        raise _deny(conn, "tenant_mismatch", "An authorization does not match this tenant and agency login", gloc)
    if gloc is not None:
        a = auths[0]
        if others:
            raise _deny(conn, "duplicate_mapping", "Another business also holds an open authorization for this Google location", gloc)
        if a.target_type == GROUP and (not group or a.target_account_name != group):
            raise _deny(conn, "group_mismatch", "The location's authorization targets a different Location Group than the agency login's", gloc)
        resource = location_resource(gloc)
        if a.google_location_resource and a.google_location_resource != resource:
            raise _deny(conn, "location_mismatch", "The authorization was recorded for a different Google location", gloc)
        if not a.agency_account_name or gloc.google_account_name != a.agency_account_name:
            raise _deny(conn, "location_not_in_group", "The location is not recorded under the account the agency login sees it through", gloc)
        audit(db, action="google.agency.used", tenant_id=conn.tenant_id, entity_type="google_agency_authorization", entity_id=a.id,
              meta={"location": resource, "group": bool(group), "project": settings.google_agency_project_model or "undecided"})
        return AgencyAccess(conn.tenant_id, conn.id, conn.agency_account_id, group, (a.id,), resource)
    return AgencyAccess(conn.tenant_id, conn.id, conn.agency_account_id, group, tuple(a.id for a in auths), None)


def token_for_connection(db: Session, conn: GoogleConnection, provider=None, gloc: GoogleLocation | None = None) -> str:
    """Called by tokens.get_access_token ONLY for agency_account connections. Resolves the explicit mapping first (resolve_agency_access: it fails closed), then returns the agency login's token."""
    access = resolve_agency_access(db, conn, gloc)
    return agency_access_token(access.agency_account_id, provider)


def _agency_email(account_id: uuid.UUID) -> str:
    with _platform() as s:
        row = s.get(GoogleAgencyAccount, account_id)
        if row is None or row.status != "active":
            raise g.GoogleAgencyUnavailable("The agency account is not active")
        return row.google_email


def pick_account(need: int = 1) -> tuple[uuid.UUID, str, str | None]:
    """(agency Google user, invitation target type, LocationGroup or None) for a new client.

    A login that belongs to a LocationGroup is ALWAYS preferred and is invited as that group. A login without one is used only when GOOGLE_AGENCY_INDIVIDUAL_FALLBACK is on. Within each kind the
    least loaded login that can take `need` more without passing its cap wins. The cap is a CONFIG value; 0/NULL means unknown, not unlimited. TODO(verify): Google's limit for locations
    managed from one account or group."""
    with _platform() as s:
        best: dict[str, tuple[int, uuid.UUID, str | None] | None] = {GROUP: None, INDIVIDUAL: None}
        for a in s.scalars(select(GoogleAgencyAccount).where(GoogleAgencyAccount.status == "active").order_by(GoogleAgencyAccount.created_at)):
            n = s.scalar(select(func.count(func.distinct(Auth.google_location_id))).where(Auth.agency_account_id == a.id, Auth.status.in_(LIVE))) or 0
            cap = a.max_locations or settings.google_agency_max_locations_per_account or None
            if cap and n + need > cap:
                continue
            kind = GROUP if a.location_group_name else INDIVIDUAL
            if best[kind] is None or n < best[kind][0]:
                best[kind] = (n, a.id, a.location_group_name)
        if best[GROUP]:
            return best[GROUP][1], GROUP, best[GROUP][2]
        if best[INDIVIDUAL] and settings.google_agency_individual_fallback:
            return best[INDIVIDUAL][1], INDIVIDUAL, None
        raise NoAgencyAccount("No agency account can take this client")


# ------------------------------------------------------------------ consent
def _open_auths(db: Session, conn_id: uuid.UUID, states=LIVE) -> list[Auth]:
    return list(db.scalars(select(Auth).where(Auth.connection_id == conn_id, Auth.status.in_(states)).order_by(Auth.created_at)))


def _selected_glocs(db: Session, conn_id: uuid.UUID) -> list[GoogleLocation]:
    return list(db.scalars(select(GoogleLocation).where(GoogleLocation.connection_id == conn_id, GoogleLocation.selected.is_(True)).order_by(GoogleLocation.title)))


def location_resource(gl: GoogleLocation) -> str:
    """`locations/<id>` as Google names it: the same for every business, unlike the per-business row."""
    return f"locations/{location_key(gl.google_location_name)}"


def validate_scope(glocs: list[GoogleLocation], scope: str) -> None:
    """The two routes the client can choose. `location` is for ONE selected profile; `business_group` for several selected profiles that sit in the same Google business group (the same account).
    Both send one location-level invitation per profile: an account-level invitation to a business group is NOT used (Google's pages do not document it for a Location Group)."""
    if scope not in ("location", "business_group"):
        raise ScopeInvalid("Choose either one profile or your business group")
    if scope == "location" and len(glocs) != 1:
        raise ScopeInvalid("The single-profile route is for exactly one selected profile. Select just that profile, or choose the business-group route.")
    if scope == "business_group" and (len(glocs) < 2 or len({gl.google_account_name for gl in glocs}) != 1):
        raise ScopeInvalid("The business-group route is for two or more selected profiles that belong to the same Google business group.")


def _location_taken(resource: str, exclude_connection: uuid.UUID) -> bool:
    """Is another connection (in ANY business) already onboarding or managing this Google location? A platform session is needed: row-level security hides other businesses, and this must not."""
    with _platform() as s:
        return bool(s.scalar(select(func.count()).select_from(Auth).where(Auth.google_location_resource == resource, Auth.connection_id != exclude_connection, Auth.status.in_(LIVE))))


def record_consent(db: Session, *, conn: GoogleConnection, user, agree: bool, version: str, scope: str | None = None, request_id: str | None = None) -> list[Auth]:
    """Store the client's agreement for every selected location of the connection. Repeating it reuses what is open. Refused unless the client agreed to THIS text.

    `scope` is the route the client chose (validated when given; inferred when not). `request_id` makes a replay harmless: the same id returns what already exists, and an id whose authorization has
    since ended is refused instead of starting a new invitation. A Google location that another business is already onboarding or managing is refused (never mapped twice)."""
    if not enabled():
        raise AgencyDisabled("Agency management is not available")
    if agree is not True or version != CONSENT_VERSION:
        raise ConsentRequired("The client must agree to the current wording")
    if request_id:
        prior = list(db.scalars(select(Auth).where(Auth.tenant_id == conn.tenant_id, Auth.consent_request_id == request_id)))
        if prior:
            if all(p.connection_id == conn.id and p.status in LIVE for p in prior):
                return prior  # a replay of a request that is still in progress: nothing new happens
            raise ReplayDetected("This request was already used. Start again from the beginning.")
    if conn.status != GoogleConnectionStatus.active:
        raise AgencyError("Pick the locations to manage first")
    if conn.auth_mode == "agency_account":
        return _open_auths(db, conn.id)
    glocs = _selected_glocs(db, conn.id)
    if not glocs:
        raise AgencyError("No selected Google location on this connection")
    if scope is not None:
        validate_scope(glocs, scope)
    route = scope or ("location" if len(glocs) == 1 else "business_group")
    existing = {a.google_location_id: a for a in _open_auths(db, conn.id)}
    for gl in glocs:
        if gl.id not in existing and _location_taken(location_resource(gl), conn.id):
            raise LocationAlreadyManaged("This Google profile is already being set up or managed through FlowQR by another account. If it is yours, contact FlowQR support.")
    seed = next((a for a in existing.values() if a.agency_account_id), None)  # a connection keeps ONE login and ONE target for all its locations
    account_id, target_type, target_account = (seed.agency_account_id, seed.target_type, seed.target_account_name) if seed else pick_account(len(glocs))
    now, out = utcnow(), []
    for gl in glocs:
        a = existing.get(gl.id)
        if a is None:
            a = Auth(id=uuid.uuid4(), tenant_id=conn.tenant_id, connection_id=conn.id, google_location_id=gl.id, agency_account_id=account_id, status="consented", target_type=target_type,
                     target_account_name=target_account, google_location_resource=location_resource(gl), invite_scope=route, consent_request_id=request_id,
                     consent_version=CONSENT_VERSION, consent_text_sha256=consent_sha(), consented_at=now,
                     consented_by=getattr(user, "id", None), consented_by_email=(getattr(user, "email", None) or None))
            db.add(a)
            audit(db, action="google.agency.consent", tenant_id=conn.tenant_id, user_id=getattr(user, "id", None), entity_type="google_connection", entity_id=conn.id,
                  meta={"location": gl.google_location_name, "version": CONSENT_VERSION, "target": target_type, "scope": route})
        out.append(a)
    try:
        db.commit()
    except IntegrityError:  # two businesses raced for the same Google location: the platform-wide unique index lets exactly one win
        db.rollback()
        raise LocationAlreadyManaged("This Google profile is already being set up or managed through FlowQR by another account. If it is yours, contact FlowQR support.")
    return out


# ------------------------------------------------------------------ the steps
def _transient(exc: Exception) -> bool:
    return isinstance(exc, g.GoogleRateLimited) or (isinstance(exc, g.GoogleAPIError) and exc.transient)


def _wait(a: Auth, code: str, message: str) -> None:
    """Not done yet, not broken: try again later with a growing pause. Stays in the same state."""
    a.attempts = (a.attempts or 0) + 1
    a.failure_code, a.last_error = code, message[:300]
    a.next_attempt_at = utcnow() + timedelta(minutes=min(2 ** min(a.attempts, 6), max(1, settings.google_agency_poll_minutes)))


def _stop_here(a: Auth, code: str, message: str) -> None:
    """A person has to look. Before the invite the attempt simply fails (nothing exists at Google); after it, it needs attention (an invitation or manager exists)."""
    a.failure_code, a.last_error, a.next_attempt_at = code, message[:300], None
    a.status = "failed" if not a.invite_sent_at else "needs_attention"


def _client(client):
    return client or ac.get_agency_client()


def _attention(a: Auth, code: str, message: str) -> None:
    """A person has to act, even though nothing exists at Google yet (so it is not `failed`: it can be resumed with Check again)."""
    a.failure_code, a.last_error, a.next_attempt_at, a.status = code, message[:300], None, "needs_attention"


def _group_preflight(db: Session, a: Auth, client, provider) -> bool:
    """Google's sequence only works if the Location Group's ADMINISTRATOR can act on the invitation. So BEFORE the merchant's token is used for anything, the agency Google user's own token
    must list the FlowQR group in accounts.list, typed LOCATION_GROUP (documented: the response carries each account's `type`). Not listed means the user is not an administrator of the group;
    typed ORGANIZATION means the id is the organisation's. Either way no invitation is sent. True = go ahead."""
    try:
        refuse_if_organisation(a.target_account_name)
        accounts = _client(client).list_accounts(agency_access_token(a.agency_account_id, provider))
    except AgencyError as exc:
        _attention(a, "group_is_organisation", str(exc))
        alert_internal("the configured group is the organisation", [f"Authorization {a.id}: {exc}. Nothing was sent to Google."])
        db.commit()
        return False
    except (g.GoogleAgencyUnavailable, g.GoogleNotConfigured):
        _wait(a, "agency_unavailable", "The agency account is unavailable")
        db.commit()
        return False
    except g.GoogleRateLimited:
        _wait(a, "rate_limited", "Google rate limit")
        db.commit()
        return False
    except g.GoogleAPIError as exc:
        if _transient(exc):
            _wait(a, "preflight_retry", f"Google error {exc.status}")
        else:
            _attention(a, "group_access_missing", f"The agency Google user cannot list its accounts ({exc.status})")
        db.commit()
        return False
    mine = next((x for x in accounts if x.name == a.target_account_name), None)
    if mine is None:
        _attention(a, "group_access_missing", "The agency Google user is not an administrator of the FlowQR LocationGroup")
        alert_internal("the agency login has no access to the FlowQR group", [f"Authorization {a.id}: accounts.list for the agency Google user ({_agency_email(a.agency_account_id)}) does not include {a.target_account_name}. "
                                                                              "Add the user (or a user group it belongs to) as an administrator of the group in Google, then press Check again. Nothing was sent to Google and the client's token is untouched."])
    elif mine.type != "LOCATION_GROUP":
        what = "the organisation, not a Location Group" if mine.type == "ORGANIZATION" else f"typed {mine.type or 'nothing'}, not LOCATION_GROUP"
        _attention(a, "group_is_organisation" if mine.type == "ORGANIZATION" else "group_type_unconfirmed", f"{a.target_account_name} is {what}")
        alert_internal("the configured group is not a Location Group", [f"Authorization {a.id}: {a.target_account_name} is {what}. Nothing was sent to Google."])
    else:
        return True
    db.commit()
    return False


def _claimed_by_another_tenant(conn: GoogleConnection, gl: GoogleLocation) -> bool:
    """Does ANOTHER business already hold an open agency authorization for the same GOOGLE location? Looked up with a platform session (row-level security hides other tenants).
    The database's one-open-authorization rule is per FlowQR location row, so it cannot see this: two businesses could otherwise end up mapped to one Google location, and the agency login
    (which sees every client of the group) would serve one business another's reviews."""
    key = location_key(gl.google_location_name)
    with _platform() as s:
        return bool(s.scalar(select(func.count()).select_from(Auth).join(GoogleLocation, GoogleLocation.id == Auth.google_location_id).where(
            GoogleLocation.google_location_name.in_((f"locations/{key}", key)), Auth.tenant_id != conn.tenant_id, Auth.status.in_(LIVE))))


def _adopt_existing(db: Session, conn: GoogleConnection, gl: GoogleLocation, a: Auth, client, provider) -> bool:
    """A client who ALREADY gave FlowQR's group access in Google (for example by approving the group's management request in Business Profile Manager) has nothing left to invite.
    The location is already listed under the group, so it is verified from there instead: only the AGENCY user's token is used, nothing is sent to Google, and the client's token is not touched.
    The same consent, the separate notice and the whole verify-then-switch sequence still apply. Returns True when this authorization was dealt with here (adopted, waiting, or needs a
    person), False when the location is NOT listed under the group and the normal invitation must follow.

    The proof that THIS business may hand this location over is unchanged: the location came from the client's own Google login when they connected, and they agreed in the app. What is
    added is a refusal when another business already holds an open authorization for the same Google location."""
    try:
        account = _visible_account(_client(client), agency_access_token(a.agency_account_id, provider), gl, a)
    except (g.GoogleAgencyUnavailable, g.GoogleNotConfigured, g.GoogleAuthRevoked):
        _wait(a, "agency_unavailable", "The agency account is unavailable")
        db.commit()
        return True
    except g.GoogleRateLimited:
        _wait(a, "rate_limited", "Google rate limit")
        db.commit()
        return True
    except g.GoogleAPIError as exc:
        if isinstance(exc, g.GoogleApiNotApproved):
            _attention(a, "api_not_approved", "Google has not approved FlowQR for Business Profile API access")
        elif _transient(exc):
            _wait(a, "adopt_retry", f"Google error {exc.status}")
        elif exc.status in (403, 404):
            _attention(a, "group_access_missing", "The agency Google user cannot list the FlowQR LocationGroup's locations")
            alert_internal("the agency login has no access to the FlowQR group", [f"Authorization {a.id}: the agency Google user cannot list {a.target_account_name}. Nothing was sent to Google and the client's token is untouched."])
        else:
            _attention(a, "adopt_failed", f"Google refused the check ({exc.status})")
        db.commit()
        return True
    if account is None:
        return False  # not listed under the group: the client has to invite it, exactly as before
    if _claimed_by_another_tenant(conn, gl):
        _attention(a, "location_claimed", "Another business is already managed through FlowQR for this Google location")
        alert_internal("two businesses claim one Google location", [f"Authorization {a.id}: the location is already managed for another FlowQR business. Nothing was switched; a person must decide who owns it."])
        db.commit()
        return True
    now = utcnow()  # `invite_sent_at` and `accepted_at` mean "when FlowQR recorded this access" here: nothing was invited. Stopping later must still REMOVE FlowQR, so they are set.
    a.invite_sent_at, a.accepted_at, a.receiving_account_name = now, now, account
    a.status, a.failure_code, a.last_error, a.attempts, a.next_attempt_at = "accepted", None, None, 0, None
    audit(db, action="google.agency.adopted_existing", tenant_id=a.tenant_id, entity_type="google_agency_authorization", entity_id=a.id, meta={"location": gl.google_location_name, "target": a.target_type, "invited": False})
    db.commit()
    _on_accepted(db, a, gl)
    return True


def _step_invite(db: Session, conn: GoogleConnection, gl: GoogleLocation, a: Auth, client, provider) -> None:
    from app.services.google.tokens import get_access_token

    if not a.consent_version or not a.consent_text_sha256 or not a.consented_at:  # belt and braces: the columns are NOT NULL, but no invite ever leaves without the record
        _stop_here(a, "consent_missing", "No stored consent")
        return
    if conn.auth_mode != "client_token" or conn.status != GoogleConnectionStatus.active:
        _stop_here(a, "connection_not_usable", "The Google connection is not active")
        return
    group = a.target_type == GROUP
    if group and not a.target_account_name:  # belt and braces: a database check forbids it too
        _stop_here(a, "group_missing", "No LocationGroup is recorded for this authorization")
        return
    if group and not _group_preflight(db, a, client, provider):
        return  # the merchant's token has not been touched
    if group and settings.google_agency_adopt_existing_access and _adopt_existing(db, conn, gl, a, client, provider):
        return  # FlowQR's group is already a manager of this location (or the check is waiting): nothing was invited and the merchant's token was not used
    try:
        email = _agency_email(a.agency_account_id)  # also proves the agency login is active; used ONLY for the individual fallback
        token = get_access_token(db, conn, provider)  # the CLIENT's token
        client = _client(client)
    except g.GoogleNotConfigured:
        _stop_here(a, "not_configured", "Google is not configured")
        return
    except g.GoogleAuthRevoked as exc:
        _stop_here(a, "client_token_invalid", "The Google sign-in is no longer valid" if not isinstance(exc, g.GoogleAgencyUnavailable) else "The agency account is unavailable")
        return
    try:  # a duplicate invite never starts from here: adopt one that already exists
        for adm in client.list_admins(token, gl.google_location_name):
            # A group is recognised by Admin.account. A person only by e-mail, which Google returns while the invitation is PENDING and replaces with the person's name once accepted.
            if (adm.account == a.target_account_name) if group else ((adm.email or "").lower() == email.lower()):
                a.admin_resource_name, a.invite_sent_at, a.status = adm.name or None, a.invite_sent_at or utcnow(), "invited"
                a.failure_code = a.last_error = None
                db.commit()
                return
    except g.GoogleError as exc:
        if isinstance(exc, g.GoogleAuthRevoked):
            _stop_here(a, "client_token_invalid", "Google refused the sign-in")
            return
        log.info("agency: could not list admins before inviting (%s); continuing", type(exc).__name__)
    try:
        entry = (client.invite_location_group(token, gl.google_location_name, a.target_account_name) if group  # Admin.account only: NO e-mail is ever sent for a group
                 else client.invite_manager(token, gl.google_location_name, email))
    except g.GoogleAuthRevoked:
        _stop_here(a, "client_token_invalid", "Google refused the sign-in")
        return
    except g.GoogleApiNotApproved:
        _stop_here(a, "api_not_approved", "Google has not approved FlowQR for Business Profile API access")
        return
    except g.GoogleAPIError as exc:
        if exc.status == 409:  # already invited (duplicate): adopt rather than fail. TODO(verify): the exact status and reason Google returns for a duplicate invitation
            a.invite_sent_at, a.status, a.failure_code, a.last_error = a.invite_sent_at or utcnow(), "invited", "duplicate_invite", "Google says the invitation already exists"
            db.commit()
            return
        if _transient(exc):
            _wait(a, "invite_retry", f"Google error {exc.status}")
        else:
            _stop_here(a, "invite_refused", f"Google refused the invitation ({exc.status})")
        db.commit()
        return
    except g.GoogleRateLimited:
        _wait(a, "rate_limited", "Google rate limit")
        db.commit()
        return
    a.admin_resource_name, a.invite_sent_at, a.status = entry.name, utcnow(), "invited"
    a.failure_code = a.last_error = None
    a.attempts, a.next_attempt_at = 0, None
    audit(db, action="google.agency.invited", tenant_id=a.tenant_id, entity_type="google_agency_authorization", entity_id=a.id, meta={"location": gl.google_location_name, "target": a.target_type})
    if group and entry.account and entry.account != a.target_account_name:  # Google answered for a different account than the one asked for: stop and tell a person
        _stop_here(a, "invite_target_mismatch", "Google created the invitation for a different account than FlowQR's group")
        alert_internal("Google invited the wrong account", [f"Authorization {a.id}: asked for {a.target_account_name}, Google answered with another account. Nothing was switched."])
    db.commit()


def _invitation_withdrawn(db: Session, conn: GoogleConnection, gl: GoogleLocation, a: Auth, client, provider) -> bool:
    """True only on evidence: the invitation is in neither the group's invitation list nor the group's location list (the caller checked both), it is older than a new invitation needs to appear,
    and the location's own admin list, read with the client's token while FlowQR still holds it, shows NO pending invitation at all. A list that cannot be read is not evidence, and the answer
    is False. Google offers no state for an invitation, so this cannot say WHY it is gone (withdrawn by the owner, declined, expired): it never claims to."""
    if not a.invite_sent_at or utcnow() - a.invite_sent_at < timedelta(minutes=settings.google_agency_withdrawn_after_minutes):
        return False
    if conn.auth_mode != "client_token" or conn.status != GoogleConnectionStatus.active or not conn.refresh_token_encrypted:
        return False
    from app.services.google.tokens import get_access_token

    try:
        entries = _client(client).list_admins(get_access_token(db, conn, provider), gl.google_location_name)
    except g.GoogleError:
        return False
    return not any(e.pending for e in entries)


def _step_accept(db: Session, conn: GoogleConnection, gl: GoogleLocation, a: Auth, client, provider) -> None:
    try:
        token = agency_access_token(a.agency_account_id, provider)
        client = _client(client)
    except (g.GoogleAgencyUnavailable, g.GoogleNotConfigured):
        _wait(a, "agency_unavailable", "The agency account is unavailable")
        db.commit()
        return
    inv_name = a.invitation_name
    group = a.target_type == GROUP
    try:
        if not inv_name:
            want = location_key(gl.google_location_name)
            # A group invitation is looked for in the GROUP's own list first (TODO(verify): that is where Google puts it). A refusal there means this agency user has no access to the
            # group. If it is not in that list, every account the user can see is searched, and the account it was really found under is recorded, never assumed.
            found = next((i for i in client.list_pending_invitations(token, [a.target_account_name] if group else None) if location_key(i.location_name) == want), None)
            if found is None and group and settings.google_agency_invitation_discovery:
                found = next((i for i in client.list_pending_invitations(token) if location_key(i.location_name) == want), None)
            if found is not None:
                inv_name, a.receiving_account_name = found.name, found.receiving_account
        if not inv_name:
            # Not listed: either Google has not delivered it yet, or it was already accepted. Visibility settles which.
            if _visible_account(client, token, gl, a) is not None:
                a.accepted_at = a.accepted_at or utcnow()
                a.status, a.failure_code, a.last_error = "accepted", None, None
            elif _invitation_withdrawn(db, conn, gl, a, client, provider):
                a.status, a.failure_code, a.last_error, a.next_attempt_at = "withdrawn", "invitation_withdrawn", "The invitation is no longer pending and was never accepted", None
            elif a.invite_sent_at and utcnow() - a.invite_sent_at > timedelta(hours=settings.google_agency_visibility_wait_hours):
                _stop_here(a, "invitation_not_found", "The invitation never appeared for the agency account")
            else:
                _wait(a, "invitation_pending", "Waiting for the invitation to appear")
            db.commit()
            if a.status == "accepted":
                _on_accepted(db, a, gl)
            return
        a.invitation_name = inv_name
        client.accept_invitation(token, inv_name)
    except g.GoogleAPIError as exc:
        if exc.status == 404 and a.invitation_name:  # already accepted or withdrawn: let visibility decide
            a.invitation_name = None
            _wait(a, "invitation_gone", "The invitation is no longer pending; checking whether FlowQR is already a manager")
        elif group and exc.status in (403, 404) and not isinstance(exc, g.GoogleApiNotApproved):  # the agency USER is not allowed to see or accept for the group: a person must add it to the group
            _stop_here(a, "group_access_missing", "The agency Google user cannot see or accept invitations for the FlowQR LocationGroup")
            alert_internal("the agency login has no access to the FlowQR group", [f"Authorization {a.id}: add the agency Google user ({_agency_email(a.agency_account_id)}) as an owner or manager of {a.target_account_name} in Google, then press Check again. The client's token is untouched."])
        elif _transient(exc):
            _wait(a, "accept_retry", f"Google error {exc.status}")
        else:
            _stop_here(a, "accept_failed", f"Google refused to accept the invitation ({exc.status})")
        db.commit()
        return
    except g.GoogleRateLimited:
        _wait(a, "rate_limited", "Google rate limit")
        db.commit()
        return
    except g.GoogleAuthRevoked:
        _wait(a, "agency_unavailable", "The agency login was refused")
        db.commit()
        return
    a.accepted_at, a.status, a.failure_code, a.last_error, a.attempts, a.next_attempt_at = utcnow(), "accepted", None, None, 0, None
    db.commit()
    _on_accepted(db, a, gl)


def _on_accepted(db: Session, a: Auth, gl: GoogleLocation) -> None:
    """FlowQR is now a manager: start the 48-hour clock, tell the client in a SEPARATE notice (not Google's), record it."""
    if a.notice_due_at is None:
        a.notice_due_at = (a.accepted_at or utcnow()) + timedelta(hours=settings.google_agency_notice_hours)
    audit(db, action="google.agency.accepted", tenant_id=a.tenant_id, entity_type="google_agency_authorization", entity_id=a.id, meta={"location": gl.google_location_name})
    db.commit()
    send_notice(db, a, gl)


def _listed_location(client, token: str, gl: GoogleLocation, a: Auth | None = None):
    """The location as the agency login lists it, or None. TODO(verify): which account Google lists it under after acceptance.
    For a group authorization ONLY the group's own list counts: a location visible somewhere else is not access through the group, and returns None."""
    want = location_key(gl.google_location_name)
    if a is not None and a.target_type == GROUP:
        for loc in client.list_group_locations(token, a.target_account_name):
            if location_key(loc.name) == want:
                return loc if loc.account_name == a.target_account_name else None
        return None
    for loc in client.list_visible_locations(token):
        if location_key(loc.name) == want:
            return loc
    return None


def _visible_account(client, token: str, gl: GoogleLocation, a: Auth | None = None) -> str | None:
    loc = _listed_location(client, token, gl, a)
    return loc.account_name if loc is not None else None


def _group_admin_state(client, token: str, gl: GoogleLocation, a: Auth) -> str:
    """What the location's admin list says about the FlowQR group: confirmed | pending | wrong_role | unknown. Only `pending` and `wrong_role` block; an unreadable or silent list is
    `unknown`, because it is not documented that a manager may read it or that it returns Admin.account (TODO(verify)), and the group's own location list is the proof that matters."""
    try:
        entries = client.list_admins(token, gl.google_location_name)
    except g.GoogleError:
        return "unknown"
    for adm in entries:
        if adm.account == a.target_account_name:
            if adm.pending:
                return "pending"
            if adm.role not in (None, "MANAGER"):
                return "wrong_role"
            a.admin_resource_name = a.admin_resource_name or adm.name or None
            return "confirmed"
    return "unknown"


def _step_verify(db: Session, conn: GoogleConnection, gl: GoogleLocation, a: Auth, client, provider) -> None:
    group = a.target_type == GROUP
    try:
        token = agency_access_token(a.agency_account_id, provider)
        listed = _listed_location(_client(client), token, gl, a)
        account = listed.account_name if listed is not None else None
    except (g.GoogleAgencyUnavailable, g.GoogleNotConfigured, g.GoogleAuthRevoked):
        _wait(a, "agency_unavailable", "The agency account is unavailable")
        db.commit()
        return
    except g.GoogleAPIError as exc:
        if group and exc.status in (403, 404) and not isinstance(exc, g.GoogleApiNotApproved):
            _stop_here(a, "group_access_missing", "The agency Google user cannot list the FlowQR LocationGroup's locations")
            alert_internal("the agency login has no access to the FlowQR group", [f"Authorization {a.id}: the agency Google user cannot list {a.target_account_name}. The client's token is untouched."])
        else:
            _wait(a, "verify_retry", f"Could not list locations ({type(exc).__name__})")
        db.commit()
        return
    except g.GoogleError as exc:
        _wait(a, "verify_retry", f"Could not list locations ({type(exc).__name__})")
        db.commit()
        return
    now = utcnow()
    if account is None:
        waited = now - (a.accepted_at or now)
        if waited > timedelta(hours=settings.google_agency_visibility_wait_hours):
            _stop_here(a, "not_visible", "The agency account accepted but cannot see the location")
            alert_internal("agency cannot see a location after accepting", [f"Authorization {a.id}: accepted {a.accepted_at:%Y-%m-%d %H:%M} UTC, still not listed for the agency account. The client's token is untouched."])
        else:
            _wait(a, "not_visible_yet", "Waiting for the location to appear for the agency account")
        db.commit()
        return
    if listed.place_id and gl.place_id and listed.place_id != gl.place_id:  # same id, different place: never accept it as this business's location
        _attention(a, "location_identity_mismatch", "The location Google lists has a different place id than the profile you selected")
        alert_internal("a listed location does not match the selected profile", [f"Authorization {a.id}: the Google place id of the listed location differs from the one recorded for the selected profile. Nothing was switched."])
        db.commit()
        return
    if group:
        state = _group_admin_state(_client(client), token, gl, a)
        if state in ("pending", "wrong_role"):
            if state == "pending":
                _wait(a, "group_invite_pending", "The group is listed but its invitation is still pending")
            else:
                _stop_here(a, "unexpected_role", "The FlowQR group holds a role other than Manager on this location")
                alert_internal("the FlowQR group holds an unexpected role", [f"Authorization {a.id}: expected Manager. Nothing was switched."])
            db.commit()
            return
    a.agency_account_name, a.verified_at, a.last_verified_at, a.status = account, now, now, "verified"
    a.failure_code = a.last_error = None
    a.attempts, a.next_attempt_at = 0, None
    db.commit()


_STEPS = {"consented": _step_invite, "invited": _step_accept, "accepted": _step_verify}


def _resume_state(a: Auth) -> str:
    if not a.invite_sent_at:
        return "consented"
    if not a.accepted_at:
        return "invited"
    if not a.verified_at:
        return "accepted"
    return "verified"


def _drive(db: Session, conn: GoogleConnection, a: Auth, client, provider, *, force: bool) -> None:
    for _ in range(4):  # consented -> invited -> accepted -> verified at most
        if a.status not in _STEPS:
            return
        if not force and a.next_attempt_at and a.next_attempt_at > utcnow():
            return
        before = a.status
        gl = db.get(GoogleLocation, a.google_location_id)
        a.last_polled_at = utcnow()  # when Google was last asked (there is no notification from Google: this is polling, and it stays slow)
        _STEPS[a.status](db, conn, gl, a, client, provider)
        if a.status == before:  # waiting or stuck: stop here, never spin
            return


def advance_connection(db: Session, conn: GoogleConnection, *, client=None, provider=None, force: bool = False, retry: bool = False) -> list[Auth]:
    """Move every location of a connection as far along as it can go, then switch the connection if ALL its selected locations are verified. Safe to call again at any time."""
    if not enabled():
        raise AgencyDisabled("Agency management is not available")
    auths = _open_auths(db, conn.id, WORKING + ("needs_attention",))
    if not auths and conn.auth_mode != "agency_account":
        raise ConsentRequired("No stored consent for this connection")  # no invite without a consent record
    for a in auths:
        if a.status == "needs_attention":
            if not retry:
                continue
            a.status, a.failure_code, a.last_error, a.attempts, a.next_attempt_at = _resume_state(a), None, None, 0, None
            db.commit()
        _drive(db, conn, a, client, provider, force=force or retry)
    _maybe_switch(db, conn, client=client, provider=provider)
    return auths


# ------------------------------------------------------------------ switching and revoking the client's token
def _maybe_switch(db: Session, conn: GoogleConnection, *, client=None, provider=None) -> bool:
    if conn.auth_mode != "client_token" or conn.status != GoogleConnectionStatus.active:
        return False
    if not operations_enabled():
        return False  # onboarding ends at "access verified": the client's own connection and token are left exactly as they are
    glocs = _selected_glocs(db, conn.id)
    auths = {a.google_location_id: a for a in _open_auths(db, conn.id, ("verified",))}
    if not glocs or any(gl.id not in auths or not auths[gl.id].agency_account_name for gl in glocs):
        return False
    account_ids = {auths[gl.id].agency_account_id for gl in glocs}
    targets = {(auths[gl.id].target_type, auths[gl.id].target_account_name) for gl in glocs}
    if len(account_ids) != 1 or len(targets) != 1:  # one connection, one login, one target
        return False
    now = utcnow()
    for gl in glocs:  # one transaction: the connection and every location change together or not at all
        a = auths[gl.id]
        gl.client_google_account_name = gl.client_google_account_name or gl.google_account_name
        gl.google_account_name = a.agency_account_name
        a.status, a.switched_at = "active", now
    conn.auth_mode, conn.agency_account_id, conn.agency_switched_at = "agency_account", next(iter(account_ids)), now
    audit(db, action="google.agency.switched", tenant_id=conn.tenant_id, entity_type="google_connection", entity_id=conn.id, meta={"locations": len(glocs)})
    db.commit()
    if not _keeping_client_token(conn, now):  # with a keep window the client's token waits, unused, so the switch can still be undone (rollback_to_client_token)
        revoke_client_token(db, conn, client=client)
    return True


def _other_dependents(conn: GoogleConnection) -> int:
    """Other FlowQR connections (any business) that hold a token for the SAME Google user and still run on it. Looked up with a platform session: row-level security hides other tenants."""
    if not conn.google_sub:
        return 0
    with _platform() as s:
        return s.scalar(select(func.count()).select_from(GoogleConnection).where(
            GoogleConnection.google_sub == conn.google_sub, GoogleConnection.id != conn.id, GoogleConnection.auth_mode == "client_token",
            GoogleConnection.status.in_((GoogleConnectionStatus.active, GoogleConnectionStatus.pending_selection)), GoogleConnection.refresh_token_encrypted.is_not(None))) or 0


def _keeping_client_token(conn: GoogleConnection, now: datetime) -> bool:
    """True while the client's own token is deliberately kept (encrypted, never used) after the switch: GOOGLE_AGENCY_CLIENT_TOKEN_KEEP_HOURS, counted from the switch. 0 = never kept."""
    keep = settings.google_agency_client_token_keep_hours
    return bool(keep > 0 and conn.agency_switched_at and now < conn.agency_switched_at + timedelta(hours=keep))


def rollback_to_client_token(db: Session, conn: GoogleConnection, *, user=None, provider=None) -> None:
    """Undo the switch while the client's own token is still held: the connection goes back to using the CLIENT's Google login, and the agency login stops being used for it.

    Safe by construction: it refuses unless the client's token still WORKS (it is refreshed once first; that is an OAuth call, not a Business Profile call), and nothing changes if it does not. It does
    not touch Google's side: FlowQR's group stays a manager of the location until it is removed there (or the client presses Stop), because removing it is a different decision. The authorization
    is closed as `cancelled` (failure_code `rolled_back`), so the next consent starts a fresh, audited one. Works whether or not the switch is on: it only ever REDUCES what FlowQR does."""
    from app.services.google.tokens import store_tokens

    if conn.auth_mode != "agency_account":
        raise AgencyError("This connection is not managed through the agency account")
    if not conn.refresh_token_encrypted:
        raise AgencyError("The client's own Google login is no longer held (it was revoked). Ask the client to reconnect Google instead.")
    try:
        ts = (provider or g.get_google_provider()).refresh_access_token(get_cipher().decrypt(conn.refresh_token_encrypted))
    except g.GoogleAuthRevoked:
        raise AgencyError("The client's own Google login no longer works. Nothing was changed. Ask the client to reconnect Google instead.")
    except g.GoogleError as exc:
        raise AgencyError(f"Could not check the client's own Google login ({type(exc).__name__}). Nothing was changed. Try again.")
    store_tokens(conn, refresh_token=ts.refresh_token, access_token=ts.access_token, expires_in=ts.expires_in)
    now = utcnow()
    for gl in db.scalars(select(GoogleLocation).where(GoogleLocation.connection_id == conn.id)):
        if gl.client_google_account_name:
            gl.google_account_name = gl.client_google_account_name  # the v4 paths use the client's own account again
    for a in _open_auths(db, conn.id, ("active",)):
        a.status, a.failure_code, a.last_error, a.next_attempt_at = "cancelled", "rolled_back", "Returned to the client's own Google login; FlowQR's group may still be a manager in Google", None
    conn.auth_mode, conn.agency_account_id, conn.agency_switched_at = "client_token", None, None
    audit(db, action="google.agency.rolled_back", tenant_id=conn.tenant_id, user_id=getattr(user, "id", None), entity_type="google_connection", entity_id=conn.id, meta={"at": now.isoformat()})
    db.commit()


def revoke_client_token(db: Session, conn: GoogleConnection, *, client=None) -> bool:
    """Revoke the client's own token at Google, then drop our copy. Only when Google CONFIRMS: otherwise the encrypted token is kept (and the revoke is retried) rather than
    dropped without being revoked. The switch itself is already committed and the agency account is doing the work either way."""
    if not conn.refresh_token_encrypted:
        return True
    if _other_dependents(conn):
        # Google revokes a token's GRANT (this Google user, FlowQR's project). TODO(verify): whether that also ends the user's other refresh tokens for this project. Until no other connection
        # of this Google user depends on a token, this one is kept (encrypted) and the revoke is tried again later. The switch is unaffected.
        log.info("agency: client token revoke deferred, another connection uses the same Google user")
        return False
    auths = _open_auths(db, conn.id, ("active",))
    try:
        ok = _client(client).revoke_token(get_cipher().decrypt(conn.refresh_token_encrypted))
    except Exception as exc:  # noqa: BLE001
        log.warning("agency: client token revoke raised %s", type(exc).__name__)
        ok = False
    now = utcnow()
    if ok:
        conn.refresh_token_encrypted = conn.access_token_encrypted = conn.access_token_expires_at = None
        for a in auths:
            a.client_token_revoked_at = now
        audit(db, action="google.agency.client_token_revoked", tenant_id=conn.tenant_id, entity_type="google_connection", entity_id=conn.id)
    else:
        for a in auths:
            a.client_token_revoke_attempts = (a.client_token_revoke_attempts or 0) + 1
    db.commit()
    return ok


# ------------------------------------------------------------------ the separate notice
def _notice_text(a: Auth, gl: GoogleLocation, agency_email: str) -> tuple[str, str]:
    where = gl.title or gl.google_location_name
    subject = f"FlowQR is now a manager of {where} on Google"
    who = f"FlowQR's business group ({a.target_account_name})" if a.target_type == GROUP else f"FlowQR's manager account ({agency_email})"
    body = (f"Hi,\n\nThis is a separate notice from FlowQR, not from Google.\n\n"
            f"On {a.accepted_at:%d %b %Y} {who} became a Manager of your Google Business Profile for {where}, because you asked FlowQR to manage it.\n\n"
            "What FlowQR does: it reads your reviews and, only with your approval, replies, posts and updates the profile. It is a Manager, not an Owner.\n\n"
            f"To stop it at any time: open {settings.frontend_url}/gbp/locations and press \"Stop FlowQR managing my profile\", or remove FlowQR yourself in Google "
            "(Business Profile, People and access). FlowQR stops work at once and removes itself within "
            f"{settings.google_agency_removal_business_days} business days of your request.\n")
    return subject, body


def send_notice(db: Session, a: Auth, gl: GoogleLocation | None = None) -> bool:
    """Send the client the separate notice once, and record the date. Returns True when it has been sent (now or earlier)."""
    if a.notice_sent_at:
        return True
    if not a.accepted_at:
        return False
    gl = gl or db.get(GoogleLocation, a.google_location_id)
    try:
        subject, body = _notice_text(a, gl, _agency_email(a.agency_account_id))
        to = a.consented_by_email
        if not to:
            return False
        from app.services.mailer import send_email

        ok = send_email(to, subject, body)
    except Exception as exc:  # noqa: BLE001 - an e-mail problem must not undo anything; the overdue alert covers it
        log.warning("agency notice failed: %s", type(exc).__name__)
        ok = False
    audit(db, action="email.sent" if ok else "email.failed", tenant_id=a.tenant_id, entity_type="email", meta={"kind": "agency_manager_notice"})
    if ok:
        a.notice_sent_at = utcnow()
    db.commit()
    return ok


# ------------------------------------------------------------------ stopping
def request_stop(db: Session, conn: GoogleConnection, *, user=None, client=None, provider=None) -> list[Auth]:
    """"Stop FlowQR managing my profile". Works whether or not the feature switch is on (a client must always be able to stop). All work for the client stops NOW; the removal
    from Google follows and is retried until done. Records when it was requested and the deadline."""
    now = utcnow()
    live = _open_auths(db, conn.id, LIVE)
    if not live:
        return []
    deadline = add_business_days(now, settings.google_agency_removal_business_days)
    for a in live:
        if not a.invite_sent_at:
            a.status, a.removal_requested_at = "cancelled", now  # nothing exists at Google
            continue
        a.status, a.removal_requested_at, a.removal_requested_by, a.removal_deadline_at, a.failure_code = "stopping", a.removal_requested_at or now, getattr(user, "id", None), deadline, None
    conn.status, conn.disconnected_at = GoogleConnectionStatus.disconnected, now  # everything that checks the connection now stops
    for gl in db.scalars(select(GoogleLocation).where(GoogleLocation.connection_id == conn.id)):
        gl.selected = False
    audit(db, action="google.agency.stop_requested", tenant_id=conn.tenant_id, user_id=getattr(user, "id", None), entity_type="google_connection", entity_id=conn.id,
          meta={"deadline": deadline.date().isoformat()})
    db.commit()
    for a in live:
        if a.status == "stopping":
            remove_self(db, conn, a, client=client, provider=provider)
    return live


def remove_self(db: Session, conn: GoogleConnection, a: Auth, *, client=None, provider=None) -> bool:
    """Remove FlowQR as manager (or withdraw a pending invitation) for one location. True when it is gone. Retried by housekeeping until done; a person is told near the deadline."""
    if a.status != "stopping":
        return a.status in ("stopped", "cancelled", "lost")
    gl = db.get(GoogleLocation, a.google_location_id)
    unknown_name = False  # we could not NAME the admin entry (so nothing was asked of Google): that is not Google saying "already gone"
    try:
        client = _client(client)
        accepted = bool(a.accepted_at)
        if accepted:
            token = agency_access_token(a.agency_account_id, provider)
        else:  # only invited: the client's own token (if we still hold it) withdraws the pending invitation. The connection is already disconnected, so get_access_token
            # would refuse; the stored token is used directly. If it is gone, the generic branch below keeps retrying and a person is told near the deadline.
            if not conn.refresh_token_encrypted:
                raise g.GoogleAuthRevoked("no client token")
            provider = provider or g.get_google_provider()
            token = provider.refresh_access_token(get_cipher().decrypt(conn.refresh_token_encrypted)).access_token
        name = a.admin_resource_name
        if not name:  # TODO(verify): whether a list returns the invitee's e-mail; if not, the name is unknown and a person must remove FlowQR in Google
            admins = client.list_admins(token, gl.google_location_name)
            if a.target_type == GROUP:
                name = next((x.name for x in admins if x.account == a.target_account_name), None)
            else:  # an accepted person shows by NAME, not e-mail, so this only works while still pending
                email = _agency_email(a.agency_account_id).lower()
                name = next((x.name for x in admins if (x.email or "").lower() == email), None)
        if not name:
            unknown_name = True  # a location adopted from existing group access has no resource name from an invitation, and a list may not return one
            raise g.GoogleAPIError(404, "admin resource unknown")
        client.remove_manager(token, name)
        done = True
    except g.GoogleAPIError as exc:
        done = False
        if exc.status == 404 and not unknown_name:
            done = True  # Google says it is already gone
        elif (exc.status == 403 or unknown_name) and a.accepted_at:
            try:  # TODO(verify): whether a manager may delete itself. If the agency login can no longer see the location, the client already removed it.
                done = _visible_account(_client(client), agency_access_token(a.agency_account_id, provider), gl, a) is None
            except g.GoogleError:
                done = False
        if not done:
            a.failure_code, a.last_error = "removal_refused" if exc.status in (403, 404) else "removal_retry", f"Google error {exc.status}"
    except Exception as exc:  # noqa: BLE001
        done = False
        a.failure_code, a.last_error = "removal_retry", type(exc).__name__
    if done:
        a.status, a.removed_at, a.failure_code, a.last_error = "stopped", utcnow(), None, None
        audit(db, action="google.agency.removed", tenant_id=a.tenant_id, entity_type="google_agency_authorization", entity_id=a.id, meta={"location": gl.google_location_name})
    db.commit()
    return done


def on_tenant_delete(db: Session, tenant_id: uuid.UUID, *, client=None, provider=None) -> None:
    """A business is being deleted: the records go with it, so FlowQR must leave its Google profiles NOW or a person must be told which ones. Never blocks the deletion."""
    try:
        for conn in db.scalars(select(GoogleConnection).where(GoogleConnection.tenant_id == tenant_id)).all():
            if not _open_auths(db, conn.id, LIVE):
                continue
            request_stop(db, conn, client=client, provider=provider)
            left = [a for a in _open_auths(db, conn.id, ("stopping",))]
            if left:
                alert_internal("a deleted business still has FlowQR as manager in Google", [
                    f"Connection {conn.id}: {len(left)} location(s) could not be removed from Google automatically before the business was deleted. Remove FlowQR's manager account by hand."])
    except Exception as exc:  # noqa: BLE001
        log.warning("agency: leaving a deleted business's profiles failed: %s", type(exc).__name__)
        alert_internal("could not remove FlowQR from a deleted business's profiles", [f"Tenant {tenant_id}: check its Google locations and remove FlowQR's manager account by hand."])


# ------------------------------------------------------------------ losing access
def _mark_lost(db: Session, conn: GoogleConnection, a: Auth) -> None:
    now = utcnow()
    a.status, a.lost_at = "lost", now
    if conn.auth_mode == "agency_account":  # only then is FlowQR's agency login what this connection runs on. A verified-but-not-switched client keeps their own working connection untouched.
        conn.status, conn.last_error = GoogleConnectionStatus.revoked, "FlowQR's manager access was removed in Google. All work for this profile has stopped."
    audit(db, action="google.agency.lost", tenant_id=conn.tenant_id, entity_type="google_connection", entity_id=conn.id)
    db.commit()
    alert_internal("a client removed FlowQR as manager in Google", [f"Connection {conn.id} (tenant {conn.tenant_id}): FlowQR's manager access was removed. " + ("All work for this client has stopped. " if conn.auth_mode == "agency_account" else "Their own connection is unchanged. ") + "No further agency calls will be made."])


def check_access(db: Session, conn: GoogleConnection, *, client=None, provider=None) -> str:
    """Is FlowQR still a manager on this connection's locations? 'ok' | 'lost' | 'unknown' (could not check; nothing is changed on 'unknown')."""
    auths = _open_auths(db, conn.id, ("verified", "active"))
    if not auths:
        return "ok"
    seen: dict[str | None, set[str]] = {}  # one listing per LocationGroup (or one for individuals), however many locations use it
    group = None
    try:
        token = agency_access_token(auths[0].agency_account_id, provider)
        cl = _client(client)
        for a in auths:
            group = a.target_account_name if a.target_type == GROUP else None
            if group not in seen:
                seen[group] = {location_key(x.name) for x in (cl.list_group_locations(token, group) if group else cl.list_visible_locations(token))}
    except Exception as exc:  # noqa: BLE001 - agency login trouble or Google trouble says nothing about the client
        if group and isinstance(exc, g.GoogleAPIError) and exc.status in (403, 404) and not isinstance(exc, g.GoogleApiNotApproved) and hit(f"agency-group-alert:{group}", 1, 86400):
            alert_internal("the agency login lost access to the FlowQR group", [f"{group} cannot be listed by the agency Google user. Clients on it are NOT marked lost (this is FlowQR's side), but nothing can be checked or changed until the user is a member again."])
        log.info("agency: access check inconclusive (%s)", type(exc).__name__)
        return "unknown"
    now, lost = utcnow(), False
    for a in auths:
        a.last_verified_at = now
        gl = db.get(GoogleLocation, a.google_location_id)
        visible = seen[a.target_account_name if a.target_type == GROUP else None]
        if location_key(gl.google_location_name) not in visible:
            _mark_lost(db, conn, a)
            lost = True
    db.commit()
    return "lost" if lost else "ok"


def on_permission_denied(db: Session, conn_id: uuid.UUID, *, client=None, provider=None) -> str:
    """Called when a Google call for an agency connection answers 403. One 403 proves nothing (it can be a policy or quota detail), so it asks Google whether FlowQR can still see the
    location and stops everything only if it cannot. Nothing is retried against Google."""
    conn = db.get(GoogleConnection, conn_id)
    if conn is None or conn.auth_mode != "agency_account" or conn.status != GoogleConnectionStatus.active:
        return "ok"
    return check_access(db, conn, client=client, provider=provider)


# ------------------------------------------------------------------ periodic work (flowqr.agency_housekeeping)
def housekeeping(db: Session, *, client=None, provider=None, now: datetime | None = None) -> dict:
    """Obligations always run (removals, token revokes, overdue notices); moving clients forward and re-checking access run only while the switch is on."""
    now = now or utcnow()
    out = {"advanced": 0, "checked": 0, "revoked": 0, "removed": 0, "notices": 0, "alerts": 0}

    def guarded(label, fn):
        try:
            fn()
        except Exception as exc:  # noqa: BLE001 - one failing section must not stop the others
            db.rollback()
            log.warning("agency housekeeping %s failed: %s", label, type(exc).__name__)

    def removals():
        for a in db.scalars(select(Auth).where(Auth.status == "stopping")).all():
            if remove_self(db, db.get(GoogleConnection, a.connection_id), a, client=client, provider=provider):
                out["removed"] += 1
            elif a.removal_deadline_at and now >= a.removal_deadline_at - timedelta(days=2) and (a.removal_alerted_at is None or now - a.removal_alerted_at > timedelta(days=1)):
                a.removal_alerted_at = now
                alert_internal("FlowQR must be removed from a client's profile", [f"Authorization {a.id}: removal was requested {a.removal_requested_at:%Y-%m-%d}, deadline {a.removal_deadline_at:%Y-%m-%d} UTC, last error: {a.failure_code or 'none'}. Remove FlowQR in Google if it cannot be done by API."])
                out["alerts"] += 1
        db.commit()

    def revokes():
        for conn in db.scalars(select(GoogleConnection).where(GoogleConnection.auth_mode == "agency_account", GoogleConnection.refresh_token_encrypted.is_not(None))).all():
            if _other_dependents(conn) or _keeping_client_token(conn, now):
                continue  # deliberate wait, not a failure: nothing to alert about
            if revoke_client_token(db, conn, client=client):
                out["revoked"] += 1
            else:
                stuck = [a for a in _open_auths(db, conn.id, ("active",)) if a.switched_at and now - a.switched_at > timedelta(hours=24)]
                if stuck and not stuck[0].notice_overdue_alerted_at:
                    stuck[0].notice_overdue_alerted_at = now
                    alert_internal("a client's Google token could not be revoked", [f"Connection {conn.id}: switched more than 24 hours ago, Google did not confirm the revoke. The encrypted token is still held."])
                    out["alerts"] += 1
        db.commit()

    def notices():
        for a in db.scalars(select(Auth).where(Auth.accepted_at.is_not(None), Auth.notice_sent_at.is_(None), Auth.status.in_(("accepted", "verified", "active")))).all():
            if send_notice(db, a):
                out["notices"] += 1
            elif a.notice_due_at and now > a.notice_due_at and (a.notice_overdue_alerted_at is None or now - a.notice_overdue_alerted_at > timedelta(days=1)):
                a.notice_overdue_alerted_at = now
                alert_internal("the 48-hour notice to a client is overdue", [f"Authorization {a.id}: FlowQR became manager {a.accepted_at:%Y-%m-%d %H:%M} UTC; the separate notice was due {a.notice_due_at:%Y-%m-%d %H:%M} UTC and has not been sent."])
                out["alerts"] += 1
        db.commit()

    def forward():
        if not enabled():
            return
        for cid in {a.connection_id for a in db.scalars(select(Auth).where(Auth.status.in_(WORKING))).all()}:
            conn = db.get(GoogleConnection, cid)
            if conn is not None and conn.status == GoogleConnectionStatus.active:
                advance_connection(db, conn, client=client, provider=provider)
                out["advanced"] += 1

    def verify():
        if not enabled():
            return
        cutoff = now - timedelta(hours=settings.google_agency_verify_interval_hours)
        due = {a.connection_id for a in db.scalars(select(Auth).where(Auth.status.in_(("verified", "active")))).all() if a.last_verified_at is None or a.last_verified_at < cutoff}
        for cid in due:
            conn = db.get(GoogleConnection, cid)
            if conn is not None and conn.status == GoogleConnectionStatus.active:
                check_access(db, conn, client=client, provider=provider)
                out["checked"] += 1

    for label, fn in (("removals", removals), ("revokes", revokes), ("notices", notices), ("forward", forward), ("verify", verify)):
        guarded(label, fn)
    return out


# ------------------------------------------------------------------ what the app shows (never a token)
STATUS_TEXT = {
    "consented": "Waiting to invite FlowQR to your profile", "invited": "Invitation sent. Waiting for FlowQR to accept", "accepted": "FlowQR accepted. Checking it can see your profile",
    "verified": "FlowQR can see your profile", "active": "FlowQR manages this profile as your Manager", "needs_attention": "We need to look at this. Our team has been told",
    "stopping": "Stopping. FlowQR is removing itself", "stopped": "FlowQR no longer manages this profile", "lost": "FlowQR was removed in Google. Work has stopped",
    "cancelled": "Cancelled", "failed": "This could not be set up. Nothing was changed", "withdrawn": "The invitation is no longer pending and was never accepted",
}
STATES = ("google_connected", "invitation_pending", "client_action_required", "access_verified", "connection_lost", "disconnected")
_STATE_PRIORITY = ("connection_lost", "client_action_required", "invitation_pending", "access_verified", "disconnected", "google_connected")  # the connection shows the most pressing one
_CHECK_AGAIN = ("consented", "invited", "accepted", "verified", "needs_attention")
_STOPPABLE = ("invited", "accepted", "verified", "active", "needs_attention")
_RESTARTABLE = ("withdrawn", "failed", "lost", "stopped", "cancelled")
_CLIENT_FIXES = ("client_token_invalid", "invite_refused", "connection_not_usable")  # failures only the client can fix (their Google sign-in, their rights on the profile)
VERIFIED_NOTE = ("FlowQR can see your profile. Automatic reviews, replies and posts are switched off for now, because Google's rules for this kind of access are still being confirmed. "
                 "Nothing on your profile has been or will be changed, and your own Google connection is untouched.")


def dashboard_state(a: Auth, conn_status: str = "active") -> dict:
    """One of the six states the dashboard shows, with who is waiting on whom and which buttons make sense. Evidence only: it never says 'accepted' or 'verified' unless the record does."""
    s, code = a.status, a.failure_code or ""
    ops = operations_enabled()
    waiting, client_action, headline, detail = None, False, "", ""
    if s in ("consented", "invited", "accepted"):
        state, waiting, headline = "invitation_pending", "flowqr", "Invitation pending"
        detail = {"consented": "We're sending FlowQR's invitation to Google.", "invited": "The invitation is with Google. FlowQR's team accepts it for you: there is nothing for you to do.",
                  "accepted": "FlowQR has accepted. We're checking that it can see your profile before anything else happens."}[s]
    elif s == "needs_attention" and code in _CLIENT_FIXES:
        state, client_action, headline = "client_action_required", True, "Client action required"
        detail = "Your Google sign-in is no longer valid. Reconnect Google, then press Check again."
    elif s == "needs_attention":
        state, waiting, headline = "invitation_pending", "flowqr", "Invitation pending"
        detail = "This is taking longer than expected. FlowQR's team has been told and will fix it: there is nothing for you to do."
    elif s in ("verified", "active"):
        state, headline = "access_verified", "Access verified"
        detail = "FlowQR manages this profile as your Manager. Anything public still needs your approval." if s == "active" else (
            "FlowQR can see your profile and is finishing the switch." if ops else VERIFIED_NOTE)
    elif s == "withdrawn":
        state, client_action, headline = "client_action_required", True, "Client action required"
        detail = "The invitation is no longer pending and was never accepted. Google doesn't say whether it was withdrawn, declined or expired. Send it again if you still want FlowQR to manage this profile."
    elif s == "failed":
        state, client_action, headline = "client_action_required", True, "Client action required"
        detail = ("Google did not accept the invitation. This usually means the Google account you signed in with does not own or manage this profile. Check the account, reconnect, and try again."
                  if code in _CLIENT_FIXES else "The invitation could not be sent. Nothing was changed on your profile. You can try again.")
    elif s == "lost":
        state, client_action, headline = "connection_lost", True, "Connection lost"
        detail = "FlowQR was removed from your profile in Google, so everything FlowQR did through that access has stopped. To start again, reconnect Google and send a new invitation."
    elif s == "stopping":
        state, headline, detail = "disconnected", "Disconnecting", "FlowQR has stopped work on your profile and is removing itself in Google."
    else:
        state, headline, detail = "disconnected", "Disconnected", "FlowQR does not manage this profile."
    actions = []
    if s in _CHECK_AGAIN:
        actions.append("retry")
    if code in _CLIENT_FIXES or conn_status in ("revoked", "error") or s == "lost":
        actions.append("reconnect")
    if s in _STOPPABLE:
        actions.append("disconnect")
    if s in _RESTARTABLE:
        actions.append("restart")
    return {"state": state, "headline": headline, "detail": detail, "waiting_on": waiting, "client_action": client_action, "actions": actions}


def available_routes(glocs: list[GoogleLocation]) -> dict:
    """Which of the two routes fits the profiles the client has selected, and why not the other."""
    n, accounts = len(glocs), len({gl.google_account_name for gl in glocs})
    if n == 0:
        return {"selected": 0, "available": [], "reason": "Select the profile you want FlowQR to manage first."}
    if n == 1:
        return {"selected": 1, "available": ["location"], "reason": ""}
    if accounts == 1:
        return {"selected": n, "available": ["business_group"], "reason": ""}
    return {"selected": n, "available": [], "reason": "The profiles you selected belong to different Google business groups. Select profiles from one business group, or one profile."}


def status_view(db: Session, conn: GoogleConnection) -> dict:
    rows = list(db.scalars(select(Auth).where(Auth.connection_id == conn.id).order_by(Auth.created_at.desc())))
    latest: dict[uuid.UUID, Auth] = {}
    for a in rows:
        latest.setdefault(a.google_location_id, a)
    conn_status = conn.status.value if hasattr(conn.status, "value") else str(conn.status)
    locs = []
    for gid, a in latest.items():
        gl = db.get(GoogleLocation, gid)
        d = dashboard_state(a, conn_status)
        locs.append({"google_location_id": str(gid), "title": gl.title if gl else None, "status": a.status, "target_type": a.target_type, "invite_scope": a.invite_scope, "message": STATUS_TEXT.get(a.status, a.status),
                     "state": d["state"], "headline": d["headline"], "detail": d["detail"], "waiting_on": d["waiting_on"], "client_action": d["client_action"], "actions": d["actions"],
                     "invite_sent_at": a.invite_sent_at, "accepted_at": a.accepted_at, "notice_sent_at": a.notice_sent_at, "removal_requested_at": a.removal_requested_at,
                     "removal_deadline_at": a.removal_deadline_at, "removed_at": a.removed_at, "lost_at": a.lost_at, "last_polled_at": a.last_polled_at})
    if locs:
        state = next(s for s in _STATE_PRIORITY if any(x["state"] == s for x in locs))
        worst = next(x for x in locs if x["state"] == state)
        top = {"state": state, "headline": worst["headline"], "detail": worst["detail"], "waiting_on": worst["waiting_on"], "client_action": worst["client_action"], "actions": worst["actions"]}
    elif conn_status == "active":
        top = {"state": "google_connected", "headline": "Google account connected", "detail": "Choose the profile you want FlowQR to manage and approve its access to begin.", "waiting_on": None, "client_action": False, "actions": ["start"]}
    else:
        top = {"state": "disconnected", "headline": "Disconnected", "detail": "This Google connection is not active.", "waiting_on": None, "client_action": False, "actions": ["reconnect"]}
    return {"connection_id": str(conn.id), "auth_mode": conn.auth_mode, "connection_status": conn_status, **top, "routes": available_routes(_selected_glocs(db, conn.id)),
            "operations_enabled": operations_enabled(), "api_access": conn.api_access,
            "policy_note": "An accepted agency invitation is not Google's approval of FlowQR's API access. Reviews, replies, posts and edits stay off until that approval and Google's rules for this kind of access are confirmed.",
            "locations": locs}
