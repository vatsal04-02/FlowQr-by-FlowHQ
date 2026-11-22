"""The self-service agency onboarding as ONE journey the customer (and the FlowHQ operator) can read at a glance (docs/AGENCY_SELF_SERVICE_ONBOARDING_ARCHITECTURE.md).

This module only READS. It adds no step, no Google call and no permission: the steps are services/google/agency.py (invite with the customer's credentials, accept with FlowHQ's own agency login,
verify, switch, stop). What is added here is the plain answer to "where is this business, and what is happening next", computed from EVIDENCE already on record, so the screen can never say
more than the records do:

    state     one of JOURNEY_STATES. Derived on every read from the connection, the selected location, the stored consent and the authorization's own timestamps. Nothing here is a second copy that
              could drift: the authorization's status changes are already written to the audit log by services/google/agency_audit.py (one `google.agency.transition` entry per change), and the
              timeline below reads that log.
    steps     the eight stages, each with the customer-facing wording, and a status (done | current | waiting | pending | blocked | failed). A stage is `done` only when its own evidence exists
              (for example `accept` only when accepted_at is recorded, `verify` only when verified_at is, `sync` only when Google answered a sync after the switch).
    blocked   when the path cannot go ahead for a reason that is a rule and not an error (not opened for this business, Google has not approved the project, the group login has no access, the
              location is already claimed, operations are switched off). It is shown as BLOCKED with the reason. It is never shown as progress.

No token, e-mail body, Google resource name of another business, or Google review content is ever returned.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    AuditLog, GoogleAgencyAccount, GoogleAgencyAuthorization, GoogleConnection, GoogleConnectionStatus, GoogleLocation, Location,
)
from app.models.base import utcnow
from app.services.google import agency

Auth = GoogleAgencyAuthorization

JOURNEY_STATES = (
    "NOT_STARTED", "CUSTOMER_OAUTH_PENDING", "CUSTOMER_CONSENT_PENDING", "LOCATION_SELECTION_PENDING", "MANAGER_INVITE_CREATING", "MANAGER_INVITE_PENDING",
    "AGENCY_ACCEPTANCE_PENDING", "ACCESS_VERIFICATION_PENDING", "CONNECTED", "FAILED", "REVOKED", "EXPIRED", "BLOCKED",
)

# The eight stages, in order, with the words the customer sees. `consent` is FlowQR's own agreement step; the other seven are the stages named in the product brief.
STEPS = (
    ("google", "Connecting Google account"),
    ("locations", "Finding your business locations"),
    ("select", "Selecting business location"),
    ("consent", "Approving FlowQR as your Manager"),
    ("invite", "Requesting FlowHQ manager access"),
    ("accept", "Accepting agency invitation"),
    ("verify", "Verifying access"),
    ("sync", "Synchronizing reviews"),
)
_KEYS = [k for k, _ in STEPS]

OAUTH_ATTEMPT_MINUTES = 15  # a started Google sign-in counts as "pending" for this long (the OAuth state cookie lives 10 minutes)

# Failure codes (authorization.failure_code) by what they mean. The agency module records WHY a step stopped; this decides how the journey names it.
EXPIRED_CODES = {"client_token_invalid", "invitation_not_found"}
BLOCKED_CODES = {"group_access_missing", "group_is_organisation", "group_type_unconfirmed", "api_not_approved", "location_claimed", "unexpected_role", "invite_target_mismatch",
                 "location_identity_mismatch", "group_missing", "not_configured"}
_WHO = {"client_token_invalid": "client", "invitation_not_found": "flowqr"}

STATE_COPY: dict[str, tuple[str, str]] = {
    "NOT_STARTED": ("Connect your Google Business Profile", "Sign in with the Google account that owns or manages your business, and FlowQR will take it from there."),
    "CUSTOMER_OAUTH_PENDING": ("Finish signing in to Google", "Google's sign-in window was opened but not completed. Press Connect Google to try again."),
    "LOCATION_SELECTION_PENDING": ("Choose your business location", "Pick the profile you want FlowQR to manage and match it to your FlowQR location."),
    "CUSTOMER_CONSENT_PENDING": ("Approve FlowQR as your Manager", "Read what FlowQR will do, choose what you allow, and approve. Nothing is sent to Google until you do."),
    "MANAGER_INVITE_CREATING": ("Requesting FlowHQ manager access", "We are sending FlowQR's Manager invitation to Google with your sign-in."),
    "MANAGER_INVITE_PENDING": ("Invitation sent to Google", "The invitation is with Google. FlowHQ accepts it on its side: there is nothing for you to do."),
    "AGENCY_ACCEPTANCE_PENDING": ("Accepting agency invitation", "FlowHQ's agency login is accepting the invitation. This usually takes a minute."),
    "ACCESS_VERIFICATION_PENDING": ("Verifying access", "FlowHQ accepted. We are checking that it can see exactly your profile before anything else happens."),
    "CONNECTED": ("Connected", "FlowQR is a Manager of your profile and its access was checked against Google."),
    "FAILED": ("This could not be set up", "Nothing was changed on your profile. You can try again."),
    "REVOKED": ("FlowQR no longer manages this profile", "Access was withdrawn. You have exclusive control of your profile. You can start again at any time."),
    "EXPIRED": ("Your Google sign-in or the invitation expired", "Connect Google again to continue. Nothing was changed on your profile."),
    "BLOCKED": ("Waiting on a condition FlowQR cannot override", "This step is held back by a rule or a setting, not by an error. Nothing was changed on your profile."),
}

BLOCKED_COPY: dict[str, tuple[str, str]] = {
    "not_opened_for_business": ("flowqr", "FlowQR has not opened managed access for your business yet. Your own Google connection keeps working. Contact FlowQR to have it opened."),
    "no_agency_account": ("flowqr", "FlowQR's manager account is not available right now. Nothing was sent to Google. Please try again later."),
    "api_not_approved": ("flowqr", "Google has not approved FlowQR's Business Profile API access yet, so reviews and profile data cannot be read. Nothing is simulated in the meantime."),
    "location_taken": ("flowqr", "This Google profile is already being set up or managed through FlowQR by another account. If it is yours, contact FlowQR support."),
    "group_access_missing": ("flowqr", "FlowHQ's agency login cannot reach FlowQR's business group yet. FlowQR's team has been told and will fix it. Your profile was not changed."),
    "group_is_organisation": ("flowqr", "FlowQR's configuration points at the wrong kind of Google account. FlowQR's team has been told. Nothing was sent to Google."),
    "group_type_unconfirmed": ("flowqr", "Google did not confirm FlowQR's business group. FlowQR's team has been told. Nothing was sent to Google."),
    "location_claimed": ("flowqr", "Another business is already managed through FlowQR for this Google location. A person at FlowQR must decide who owns it."),
    "unexpected_role": ("flowqr", "Google lists FlowQR with a role other than Manager on this profile. Nothing was switched, and FlowQR's team has been told."),
    "invite_target_mismatch": ("flowqr", "Google answered for a different account than the one asked for. Nothing was switched, and FlowQR's team has been told."),
    "location_identity_mismatch": ("flowqr", "The profile Google lists is not the one you selected, so nothing was switched. FlowQR's team has been told."),
    "group_missing": ("flowqr", "FlowQR's configuration has no business group. Nothing was sent to Google."),
    "not_configured": ("flowqr", "Google sign-in is not configured on this FlowQR server yet."),
    "operations_off": ("flowqr", "Access is verified. Automatic review synchronization through FlowQR's manager access is not switched on yet, so it is not running. Your reviews keep syncing through your own Google sign-in."),
}

EVENT_LABEL = {
    "google.connect_started": "Google sign-in started", "google.connect": "Google account connected", "google.select_locations": "Business location selected",
    "google.agency.consent": "You approved FlowQR as your Manager", "google.agency.journey_started": "Onboarding started", "google.agency.invited": "Manager invitation sent to Google",
    "google.agency.accepted": "FlowHQ accepted the invitation", "google.agency.adopted_existing": "FlowQR's access was already in place and was checked",
    "google.agency.switched": "Connection moved onto FlowQR's manager access", "google.agency.initial_sync_queued": "First review synchronization queued",
    "google.agency.client_token_revoked": "Your own Google sign-in was revoked", "google.agency.client_oauth_revoked": "Your Google sign-in was revoked at Google",
    "google.agency.stop_requested": "You asked FlowQR to stop", "google.agency.removed": "FlowQR removed itself as a Manager", "google.agency.lost": "FlowQR's manager access was removed in Google",
    "google.agency.rolled_back": "Returned to your own Google sign-in", "google.agency.resolution_denied": "A use of the access was refused (mapping check)",
    "google.disconnect": "Google disconnected", "email.sent": "A notice was e-mailed to you", "email.failed": "A notice could not be e-mailed",
}
_TIMELINE_ACTIONS = tuple(EVENT_LABEL) + ("google.agency.transition",)  # not "used": that is written on every sync and would bury the story


def _conn_status(conn: GoogleConnection) -> str:
    return conn.status.value if hasattr(conn.status, "value") else str(conn.status)


def _blocked(code: str) -> dict:
    who, message = BLOCKED_COPY.get(code, ("flowqr", "A condition outside your control is holding this back."))
    return {"code": code, "who": who, "message": message}


# ------------------------------------------------------------------ gates that hold a business back BEFORE anything is sent
def _gate(db: Session, tenant_id: uuid.UUID, conn: GoogleConnection | None, gl: GoogleLocation | None) -> str | None:
    """The first rule (if any) that stops THIS business from starting. Read-only; sends nothing to Google."""
    if agency.internal_only() and not agency.tenant_allowed(tenant_id):
        return "not_opened_for_business"
    if conn is not None and conn.api_access in ("awaiting_approval", "api_disabled"):
        return "api_not_approved"
    if gl is not None and agency._location_taken(agency.location_resource(gl), conn.id if conn else uuid.uuid4()):
        return "location_taken"
    try:
        agency.pick_account(1)
    except agency.NoAgencyAccount:
        return "no_agency_account"
    except Exception:  # noqa: BLE001 - an unreadable platform table is "not available", never "available"
        return "no_agency_account"
    return None


# ------------------------------------------------------------------ one location
def _latest_auths(db: Session, conn: GoogleConnection) -> dict[uuid.UUID, Auth]:
    out: dict[uuid.UUID, Auth] = {}
    for a in db.scalars(select(Auth).where(Auth.connection_id == conn.id).order_by(Auth.created_at.desc())):
        out.setdefault(a.google_location_id, a)
    return out


def _resume_step(a: Auth) -> str:
    """The state a stalled authorization is waiting in, from what is recorded (not from a status name)."""
    if not a.invite_sent_at:
        return "MANAGER_INVITE_CREATING"
    if not a.accepted_at:
        return "AGENCY_ACCEPTANCE_PENDING" if a.invitation_name else "MANAGER_INVITE_PENDING"
    return "ACCESS_VERIFICATION_PENDING"


def location_state(db: Session, conn: GoogleConnection, gl: GoogleLocation | None, a: Auth | None) -> tuple[str, str | None]:
    """(state, blocked_code) for one location of a connection."""
    cs = _conn_status(conn)
    if a is None:
        blocked_api = conn.api_access in ("awaiting_approval", "api_disabled")
        if cs == "revoked":
            return "EXPIRED", None
        if cs == "disconnected":
            return "NOT_STARTED", None
        if cs == "error":
            return ("BLOCKED", "api_not_approved") if blocked_api else ("FAILED", None)
        if gl is None or not gl.selected:
            return ("BLOCKED", "api_not_approved") if blocked_api else ("LOCATION_SELECTION_PENDING", None)
        gate = _gate(db, conn.tenant_id, conn, gl)
        return ("BLOCKED", gate) if gate else ("CUSTOMER_CONSENT_PENDING", None)
    s, code = a.status, a.failure_code or ""
    if s in ("stopping", "stopped", "cancelled", "lost"):
        return "REVOKED", None
    if s == "consented":
        return "MANAGER_INVITE_CREATING", None
    if s == "invited":
        return ("AGENCY_ACCEPTANCE_PENDING" if a.invitation_name else "MANAGER_INVITE_PENDING"), None
    if s == "accepted":
        return "ACCESS_VERIFICATION_PENDING", None
    if s in ("verified", "active"):
        return "CONNECTED", None
    if s == "needs_attention":
        if code in EXPIRED_CODES:
            return "EXPIRED", None
        if code in BLOCKED_CODES:
            return "BLOCKED", code
        return _resume_step(a), None  # a person at FlowQR has been told; the step it waits in is still the honest answer
    if s == "withdrawn":
        return "FAILED", None
    if s == "failed":
        if code in EXPIRED_CODES:
            return "EXPIRED", None
        if code in BLOCKED_CODES:
            return "BLOCKED", code
        return "FAILED", None
    return "FAILED", None


def _reached(conn: GoogleConnection | None, found: int, selected: bool, a: Auth | None, gl: GoogleLocation | None) -> int:
    """How many of the eight stages have their OWN evidence on record."""
    n = 0
    if conn is not None and conn.connected_at:
        n = 1
        if found > 0:
            n = 2
            if selected or a is not None:  # an authorization means it WAS selected, even if a stop has since cleared the tick
                n = 3
                if a is not None:
                    n = 4
                    if a.invite_sent_at:
                        n = 5
                        if a.accepted_at:
                            n = 6
                            if a.verified_at:
                                n = 7
                                if a.status == "active" and gl is not None and gl.last_sync_status == "ok" and gl.last_synced_at and a.switched_at and gl.last_synced_at >= a.switched_at:
                                    n = 8
    return n


_TERMINAL = {"FAILED": "failed", "EXPIRED": "failed", "BLOCKED": "blocked", "REVOKED": "failed"}
_WAITING = {"MANAGER_INVITE_PENDING", "AGENCY_ACCEPTANCE_PENDING", "ACCESS_VERIFICATION_PENDING", "MANAGER_INVITE_CREATING"}


def build_steps(state: str, blocked_code: str | None, reached: int, a: Auth | None, found: int = 1) -> list[dict]:
    """The eight stages with a status each. `done` only where `reached` (evidence) says so; the next one is `current`/`waiting`/`blocked`/`failed` according to the state; the rest are `pending`."""
    out = []
    ops = agency.operations_enabled()
    for i, (key, label) in enumerate(STEPS):
        if i < reached:
            status, msg = "done", None
        elif i == reached:
            if state == "REVOKED":
                status, msg = "pending", None  # ended on purpose: nothing failed
            elif state == "LOCATION_SELECTION_PENDING" and found == 0:
                status, msg = "current", "Google lists no Business Profile location for this account. Connect the Google account that owns or manages your listing."
            elif state in _TERMINAL:
                status = _TERMINAL[state]
                msg = _blocked(blocked_code)["message"] if state == "BLOCKED" and blocked_code else STATE_COPY[state][1]
            elif state == "CONNECTED" and key == "sync":
                if a is not None and a.status == "verified" and not ops:
                    status, msg = "blocked", BLOCKED_COPY["operations_off"][1]
                elif a is not None and a.status == "verified":
                    status, msg = "waiting", "Access is verified. Moving the connection onto FlowQR's manager access."
                else:
                    status, msg = "waiting", "The first review synchronization has been queued and has not finished yet."
            elif state in _WAITING:
                status, msg = "waiting", STATE_COPY[state][1]
            else:
                status, msg = "current", STATE_COPY.get(state, ("", ""))[1]
        else:
            status, msg = "pending", None
        out.append({"key": key, "label": label, "status": status, "message": msg})
    return out


def mapping_checks(db: Session, conn: GoogleConnection, gl: GoogleLocation, a: Auth | None) -> list[dict]:
    """The deterministic mapping, one check per property that must hold. Platform-wide counts use a platform session (row-level security hides other businesses from this one, and this must not)."""
    checks = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": detail})

    add("google_account", bool(conn.google_sub and conn.connected_at), "The Google identity that signed in is recorded for this business")
    add("tenant", gl.tenant_id == conn.tenant_id and (a is None or a.tenant_id == conn.tenant_id), "The location, the connection and the authorization belong to the same business")
    loc = db.get(Location, gl.location_id) if gl.location_id else None
    add("business_identity", loc is not None and loc.tenant_id == conn.tenant_id, "The Google location is matched to one of this business's own FlowQR locations")
    if a is not None:
        add("google_location", a.google_location_resource == agency.location_resource(gl), "The authorization names exactly this Google location")
        with agency._platform() as s:
            acct = s.get(GoogleAgencyAccount, a.agency_account_id) if a.agency_account_id else None
            others = s.scalar(select(func.count()).select_from(Auth).where(Auth.google_location_resource == a.google_location_resource, Auth.id != a.id,
                                                                            Auth.status.in_(agency.LIVE), Auth.tenant_id != conn.tenant_id)) or 0
            same = s.scalar(select(func.count()).select_from(Auth).where(Auth.google_location_id == gl.id, Auth.status.in_(agency.LIVE))) or 0
        add("agency_grant", acct is not None and acct.status == "active" and (a.target_type != agency.GROUP or a.target_account_name == acct.location_group_name),
            "The authorization points at an active FlowHQ agency login and the business group it belongs to")
        add("no_conflicting_tenant", others == 0, "No other business holds an open authorization for this Google location")
        add("no_duplicate_mapping", same <= 1, "Exactly one open authorization exists for this location")
        add("owner_connection_preserved", a.status == "active" or conn.auth_mode == "client_token",
            "The business's own Google connection is unchanged until the access has been verified and switched")
    return checks


def _timeline(db: Session, ids: list[str], limit: int = 40) -> list[dict]:
    if not ids:
        return []
    rows = db.scalars(select(AuditLog).where(AuditLog.entity_id.in_(ids), AuditLog.action.in_(_TIMELINE_ACTIONS)).order_by(AuditLog.created_at.desc()).limit(limit)).all()
    out = []
    for r in rows:
        meta = r.meta or {}
        if r.action == "google.agency.transition":
            out.append({"at": r.created_at, "event": f"Status changed: {meta.get('from') or 'new'} to {meta.get('to')}", "code": meta.get("code"), "action": r.action})
        elif r.action == "email.sent" or r.action == "email.failed":
            if str(meta.get("kind", "")).startswith("agency"):
                out.append({"at": r.created_at, "event": EVENT_LABEL[r.action], "code": meta.get("kind"), "action": r.action})
        else:
            out.append({"at": r.created_at, "event": EVENT_LABEL.get(r.action, r.action), "code": None, "action": r.action})
    return out


# ------------------------------------------------------------------ the whole connection
def _actions(state: str, conn: GoogleConnection | None, auths: list[Auth]) -> list[str]:
    acts: list[str] = []
    if conn is None or _conn_status(conn) in ("revoked", "error", "disconnected") or state in ("NOT_STARTED", "CUSTOMER_OAUTH_PENDING", "EXPIRED"):
        acts.append("connect")
    if state == "LOCATION_SELECTION_PENDING":
        acts.append("select_location")
    if state == "CUSTOMER_CONSENT_PENDING":
        acts.append("approve")
    if any(a.status in ("consented", "invited", "accepted", "verified", "needs_attention") for a in auths) or state == "BLOCKED":
        acts.append("check_again")
    if state in ("FAILED", "REVOKED", "EXPIRED") and conn is not None and _conn_status(conn) == "active":
        acts.append("restart")
    if any(a.status in ("invited", "accepted", "verified", "active", "needs_attention") for a in auths) or (conn is not None and _conn_status(conn) in ("active", "pending_selection")):
        acts.append("disconnect")
    return acts


_ORDER = {s: i for i, s in enumerate(JOURNEY_STATES)}
_PRESSING = ("BLOCKED", "FAILED", "EXPIRED", "REVOKED")


def _aggregate(states: list[tuple[str, str | None]]) -> tuple[str, str | None]:
    """The connection shows the most pressing location first, otherwise the LEAST advanced one (so nothing reads as done while a location is not)."""
    for p in _PRESSING:
        for s, b in states:
            if s == p:
                return s, b
    return min(states, key=lambda x: _ORDER[x[0]])


def journey_for_connection(db: Session, conn: GoogleConnection, *, operator: bool = False, compact: bool = False) -> dict:
    """`compact` leaves out the timeline and the mapping checks (the operator's list needs neither for every row)."""
    glocs = list(db.scalars(select(GoogleLocation).where(GoogleLocation.connection_id == conn.id).order_by(GoogleLocation.title)))
    latest = _latest_auths(db, conn)
    relevant = [gl for gl in glocs if gl.selected or gl.id in latest]
    locations, states = [], []
    for gl in relevant:
        a = latest.get(gl.id)
        st, code = location_state(db, conn, gl, a)
        states.append((st, code))
        reached = _reached(conn, len(glocs), gl.selected, a, gl)
        locations.append(_location_view(db, conn, gl, a, st, code, reached, operator, len(glocs), compact))
    if not relevant:
        st, code = location_state(db, conn, None, None)
        states.append((st, code))
    state, bcode = _aggregate(states)
    top_loc = next((l for l, (s, _) in zip(locations, states) if s == state), None)
    auths = [a for a in latest.values()]
    reached = min((l["reached"] for l in locations), default=_reached(conn, len(glocs), False, None, None))
    steps = top_loc["steps"] if top_loc else build_steps(state, bcode, reached, None, len(glocs))
    headline, detail = STATE_COPY[state]
    out = {
        "connection_id": str(conn.id), "state": state, "headline": headline, "detail": detail, "steps": steps,
        "blocked": _blocked(bcode) if state == "BLOCKED" and bcode else None,
        "google": {"email": conn.google_email, "connected_at": conn.connected_at, "status": _conn_status(conn), "api_access": conn.api_access, "auth_mode": conn.auth_mode,
                   "locations_found": len(glocs)},
        "actions": _actions(state, conn, auths), "locations": locations,
        "available_locations": [{"google_location_id": str(gl.id), "title": gl.title, "address": gl.address, "selected": gl.selected, "flowqr_location_id": str(gl.location_id) if gl.location_id else None,
                                 "taken": bool(agency._location_taken(agency.location_resource(gl), conn.id)) if not gl.selected else False} for gl in glocs],
        "timeline": [] if compact else _timeline(db, [str(conn.id)] + [str(a.id) for a in auths]),
        "operations_enabled": agency.operations_enabled(),
    }
    return out


def _location_view(db: Session, conn: GoogleConnection, gl: GoogleLocation, a: Auth | None, st: str, code: str | None, reached: int, operator: bool, found: int = 1, compact: bool = False) -> dict:
    ops = agency.operations_enabled()
    if a is not None and a.status == "verified" and not ops:
        sync_mode = "owner_oauth"  # onboarding ended at "access verified": the business's own sign-in keeps syncing
    else:
        sync_mode = "agency" if conn.auth_mode == "agency_account" else "owner_oauth"
    view = {
        "google_location_id": str(gl.id), "title": gl.title, "address": gl.address, "selected": gl.selected, "flowqr_location_id": str(gl.location_id) if gl.location_id else None,
        "state": st, "blocked": _blocked(code) if st == "BLOCKED" and code else None, "reached": reached, "steps": build_steps(st, code, reached, a, found),
        "sync": {"mode": sync_mode, "last_synced_at": gl.last_synced_at, "last_status": gl.last_sync_status, "last_error": gl.last_sync_error if operator else None,
                 "consecutive_failures": gl.consecutive_failures, "initial_sync_queued_at": a.initial_sync_enqueued_at if a else None},
        "authorization": None,
        "mapping": [] if compact else mapping_checks(db, conn, gl, a),
    }
    if a is not None:
        view["authorization"] = {
            "id": str(a.id), "status": a.status, "target_type": a.target_type, "consent_version": a.consent_version, "consented_at": a.consented_at, "consented_by_email": a.consented_by_email,
            "consent_actions": a.consent_actions if a.consent_actions is not None else list(agency.ACTION_CATEGORIES), "consent_actions_recorded": a.consent_actions is not None,
            "invite_sent_at": a.invite_sent_at, "accepted_at": a.accepted_at, "verified_at": a.verified_at, "last_verified_at": a.last_verified_at, "switched_at": a.switched_at,
            "notice_due_at": a.notice_due_at, "notice_sent_at": a.notice_sent_at, "removal_requested_at": a.removal_requested_at, "removal_deadline_at": a.removal_deadline_at,
            "removed_at": a.removed_at, "lost_at": a.lost_at, "notices_sent": a.notices_sent or {},
        }
        if operator:
            view["authorization"].update({"failure_code": a.failure_code, "last_error": a.last_error, "attempts": a.attempts, "next_attempt_at": a.next_attempt_at,
                                          "last_polled_at": a.last_polled_at, "google_location_resource": a.google_location_resource, "invite_scope": a.invite_scope})
    return view


def journey_for_tenant(db: Session, tenant_id: uuid.UUID, *, now: datetime | None = None) -> dict:
    """The customer's whole picture: one journey per Google connection that is not disconnected, or the starting state when there is none."""
    now = now or utcnow()
    conns = db.scalars(select(GoogleConnection).where(GoogleConnection.tenant_id == tenant_id).order_by(GoogleConnection.created_at)).all()
    live = [c for c in conns if _conn_status(c) != "disconnected"]
    # A connection that ended but whose stop is still being carried out (or just finished) is still shown: the customer should see "FlowQR is removing itself", not an empty page.
    recent = [c for c in conns if _conn_status(c) == "disconnected" and db.scalar(select(func.count()).select_from(Auth).where(
        Auth.connection_id == c.id, Auth.updated_at >= now - timedelta(days=14)))]
    journeys = [journey_for_connection(db, c) for c in live + recent]
    out: dict = {"journeys": journeys}
    if not journeys:
        started = db.scalar(select(func.max(AuditLog.created_at)).where(AuditLog.tenant_id == tenant_id, AuditLog.action == "google.connect_started"))
        done = db.scalar(select(func.max(AuditLog.created_at)).where(AuditLog.tenant_id == tenant_id, AuditLog.action == "google.connect"))
        pending = bool(started and started >= now - timedelta(minutes=OAUTH_ATTEMPT_MINUTES) and (done is None or done < started))
        state = "CUSTOMER_OAUTH_PENDING" if pending else "NOT_STARTED"
        gate = "not_opened_for_business" if agency.internal_only() and not agency.tenant_allowed(tenant_id) else None
        if gate:
            state = "BLOCKED"
        headline, detail = STATE_COPY[state]
        out["start"] = {"state": state, "headline": headline, "detail": detail, "blocked": _blocked(gate) if gate else None, "actions": [] if gate else ["connect"],
                        "steps": build_steps(state, gate, 0, None)}
    return out
