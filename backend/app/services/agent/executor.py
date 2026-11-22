"""The controlled execution service for Google Business Profile changes. Every profile write the agent makes goes through `execute`.

    propose      one AgentAction, classified by the policy (never by the model), validated against verified facts; BLOCKED (and not executable) if the evidence is
                 insufficient or conflicting; otherwise either waiting for a person (pending_approval) or authorised by policy / a standing pre-authorisation (approved)
    decide       a person approves or rejects one action. The approval is bound to that exact value, the Google value it was judged against and the facts it relied on
    execute      re-checks EVERYTHING at the moment of execution, then: claim (committed) -> write -> read the profile back from Google -> compare -> record
    recover      an action left "executing" by a crash is resolved by reading Google, never by blindly writing again

Nothing is "executed" because a request was sent. It is executed only when a separate read of the profile from Google shows the new value. Every step is appended to
the hash-chained history (history.py)."""
from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import hit
from app.models import (
    AgentAction, AgentActionApproval, AgentSettings, GbpSnapshot, GoogleConnection, GoogleConnectionStatus, GoogleLocation, Role, Tenant,
)
from app.models.autonomy import LIVE_STATUSES
from app.models.base import utcnow
from app.models.tenancy import ROLE_RANK
from app.services import consent as consent_svc
from app.services import entitlements as ent
from app.services import google as g
from app.services.agent import autonomy_policy as pol
from app.services import usage as api_usage
from app.services.agent import controls, history, learning
from app.services.agent import knowledge as kbs
from app.services.agent.posts import describe_failure
from app.services.agent.v2 import field_ops
from app.services.agent.v2 import gate as v2gate
from app.services.agent.v2 import present
from app.services.audit import audit
from app.services.google.tokens import get_access_token, note_not_approved

log = logging.getLogger("flowqr.autonomy")
EXPECTED_OUTCOME = ("Customers see accurate, complete information on your profile. Search visibility may or may not change: FlowQR measures it afterwards "
                    "and never claims a change was caused by this.")
AUTONOMOUS_BASES = ("level1_policy", "preauthorization")


class ActionError(Exception):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def get_settings(db: Session, tenant_id: uuid.UUID) -> AgentSettings:
    s = db.scalar(select(AgentSettings).where(AgentSettings.tenant_id == tenant_id))
    if s is None:
        s = AgentSettings(tenant_id=tenant_id)
        db.add(s)
        db.flush()
    return s


def _tenant_facts(tenant: Tenant) -> dict:
    return {"website": tenant.website, "phone": tenant.phone, "address": tenant.address}


def _scope(a: AgentAction) -> dict:
    return {"action_type": a.action_type, "effective_type": a.effective_type, "field_key": a.field_key, "google_location_id": str(a.google_location_id),
            "value_hash": a.value_hash, "base_fingerprint": a.base_fingerprint, "facts_fingerprint": a.facts_fingerprint}


def _add_approval(db: Session, a: AgentAction, decision: str, basis: str, user_id, reason: str | None, now: datetime, ttl: timedelta | None) -> AgentActionApproval:
    sc = _scope(a)
    ap = AgentActionApproval(tenant_id=a.tenant_id, action_id=a.id, decision=decision, basis=basis, authorized_by=user_id, reason=reason, decided_at=now,
                             expires_at=(now + ttl) if ttl else None, scope=sc, scope_hash=pol.fingerprint(sc))
    db.add(ap)
    db.flush()
    return ap


def _valid_approval(db: Session, a: AgentAction) -> AgentActionApproval | None:
    return db.scalar(select(AgentActionApproval).where(AgentActionApproval.action_id == a.id, AgentActionApproval.invalidated_at.is_(None))
                     .order_by(AgentActionApproval.decided_at.desc()).limit(1))


def _gloc_conn(db: Session, a: AgentAction):
    gloc = db.get(GoogleLocation, a.google_location_id)
    conn = db.get(GoogleConnection, gloc.connection_id) if gloc else None
    return gloc, conn


# =============================================================================================================================================
# propose
# =============================================================================================================================================
def propose(db: Session, tenant: Tenant, gloc: GoogleLocation, action_type: str, *, proposed, source: dict, trigger: str, problem: str, reason: str,
            field_key: str | None = None, evidence: dict | None = None, expected_outcome: str | None = None, proposed_by: str = "agent",
            user_id: uuid.UUID | None = None, task_id: uuid.UUID | None = None, now: datetime | None = None, info_override: dict | None = None,
            relaxed: bool = False, force_owner: bool = False) -> AgentAction:
    """Create (or return the existing) action for one change. The policy level, risk and who may authorise it are computed HERE from the action type and the values;
    there is no parameter through which a caller or a model could supply them. Caller commits."""
    now = now or utcnow()
    spec = pol.SPECS.get(action_type)
    if spec is None:
        raise pol.PolicyError(f"Unknown action type '{action_type}'.")
    if spec.internal:
        raise pol.PolicyError(f"'{spec.label}' is internal analysis, not a Google change.")
    if gloc.tenant_id != tenant.id:
        raise pol.PolicyError("That location does not belong to this business.")
    if proposed_by not in ("agent", "user"):
        raise pol.PolicyError("proposed_by must be agent or user.")
    fk = spec.field or field_key
    if not fk:
        raise pol.PolicyError(f"'{action_type}' needs a field.")
    srow = get_settings(db, tenant.id)
    snap = db.scalar(select(GbpSnapshot).where(GbpSnapshot.google_location_id == gloc.id))
    info = info_override if info_override is not None else (snap.info if snap is not None else None)  # a person's own edit is judged against what Google holds RIGHT NOW
    current = pol.field_value(info, fk) if info is not None else None
    prop_c = pol.canon(fk, proposed)
    kb, tf = kbs.context(db, tenant), _tenant_facts(tenant)
    decision = pol.classify(action_type, field_key=fk, current=current, proposed=prop_c, kb=kb)
    problems = pol.validate_proposal(action_type, field_key=fk, current=current, proposed=prop_c, source=source or {}, proposed_by=proposed_by, kb=kb, tenant_facts=tf, relaxed=relaxed,
                                     info=info)
    if info is None:
        problems.append("FlowQR has no recent copy of this Google profile, so it cannot tell what is there now. Refresh from Google first.")
    if pol.permission_off(action_type, srow.autonomy_permissions):
        problems.append(f"'{spec.label}' is switched off in your autonomy settings.")
    if not decision.writable:
        problems.append(f"FlowQR cannot write '{decision.label}' to Google through its current integration. A person can change it in Google Business Profile.")
    if proposed_by == "agent":
        sup = learning.suppression(db, tenant.id, gloc.id, action_type, fk, now)
        if sup:
            problems.append(sup)
    base_fp, value_hash = pol.fingerprint(current), pol.fingerprint(prop_c)
    facts_fp = pol.facts_fingerprint(action_type, source or {}, kb, tf, prop_c)
    key = pol.fingerprint({"t": str(tenant.id), "l": str(gloc.id), "ty": decision.effective_type, "f": fk, "v": value_hash, "b": base_fp})
    # An identical live action is never duplicated. A recently BLOCKED one is only reused for the agent's own repeat proposals: a person asking for the same change
    # is a new decision (the earlier block may have been the agent's own pause) and gets its own action.
    recently_blocked = (AgentAction.status == "blocked") & (AgentAction.created_at >= now - timedelta(days=7)) if proposed_by == "agent" else None
    dup = db.scalar(select(AgentAction).where(AgentAction.tenant_id == tenant.id, AgentAction.idempotency_key == key,
                                              (AgentAction.status.in_(LIVE_STATUSES)) if recently_blocked is None else ((AgentAction.status.in_(LIVE_STATUSES)) | recently_blocked)).limit(1))
    if dup is not None:
        return dup  # the same change against the same Google value is already known: never a second action
    authz = pol.authorization_for(decision, autonomy_enabled=srow.autonomy_enabled, suspended=bool(srow.autonomy_suspended_at), permissions=srow.autonomy_permissions)
    if force_owner:  # a person is making this change right now: it is authorised by that person (decide / approve_now), never by standing policy
        authz = "owner"
    if authz in ("policy", "preauthorized") and not ent.for_tenant(db, tenant.id).has("autonomy"):
        authz = "owner"  # the plan does not include autonomous maintenance: a person decides every change
    if authz in ("policy", "preauthorized") and not consent_svc.has_active(db, tenant.id, gloc.id, decision.effective_type):
        authz = "owner"  # no express consent for THIS location and THIS action type (decision D2): a person decides every change
    gate = v2gate.status_for(gloc, fk)
    held_by_gate = bool(gate["applies"] and not gate["allowed"])
    if held_by_gate:  # V2 field on a customer profile while the policy gate is closed: drafted and shown, never approved into execution
        authz = "owner"
        decision.reasons.append(gate["reason"])
    status = "blocked" if problems else ("recommended" if held_by_gate else ("approved" if authz in ("policy", "preauthorized") else "pending_approval"))
    a = AgentAction(
        tenant_id=tenant.id, google_location_id=gloc.id, task_id=task_id, action_type=action_type, field_key=fk, trigger=trigger[:60], problem=problem, reason=reason,
        expected_outcome=expected_outcome or EXPECTED_OUTCOME, evidence=evidence or {}, source=source or {}, current_value={"value": current},
        proposed_value={"value": proposed, "canonical": prop_c}, base_fingerprint=base_fp, value_hash=value_hash, facts_fingerprint=facts_fp, idempotency_key=key,
        policy_level=decision.level, effective_type=decision.effective_type, risk_level=decision.risk, policy_reasons=decision.reasons, authorization=authz,
        status=status, proposed_by=proposed_by, proposed_by_user=user_id if proposed_by == "user" else None,
        expires_at=now + timedelta(days=settings.autonomy_proposal_ttl_days) if status == "pending_approval" else None,
        last_error="; ".join(problems)[:1000] if problems else None,
    )
    try:
        with db.begin_nested():
            db.add(a)
            db.flush()
    except IntegrityError:
        # Only the duplicate-proposal race is expected here (another worker proposed the same change a moment ago). Anything else is a real error and must not be hidden.
        racing = db.scalar(select(AgentAction).where(AgentAction.tenant_id == tenant.id, AgentAction.idempotency_key == key, AgentAction.status.in_(LIVE_STATUSES)).limit(1))
        if racing is None:
            raise
        return racing
    history.record(db, a, "proposed", actor=proposed_by, user_id=user_id, now=now, data={
        "action_type": action_type, "field": fk, "trigger": trigger, "problem": problem, "reason": reason, "current": current, "proposed": prop_c, "source": source,
        "evidence": evidence or {}, "expected_outcome": a.expected_outcome})
    history.record(db, a, "policy_classified", actor="system", now=now, data={"level": decision.level, "label": pol.LABELS[decision.level], "effective_type": decision.effective_type,
                                                                              "risk": decision.risk, "reasons": decision.reasons, "authorization": authz, "writable": decision.writable})
    if problems:
        history.record(db, a, "blocked", actor="system", now=now, data={"problems": problems})
    elif status == "recommended":
        history.record(db, a, "recommended", actor="system", now=now, data={"why": "the customer-write policy gate is closed for this profile", "gate": {k: gate[k] for k in ("test_profile", "customer_writes")},
                                                                           "owner_can": "make this change in Google Business Profile"})
    elif status == "approved":
        basis = "level1_policy" if authz == "policy" else "preauthorization"
        ap = _add_approval(db, a, "auto_authorized", basis, None, f"Authorised by {pol.LABELS[decision.level]} policy" + (" with a pre-authorisation for this action type." if authz == "preauthorized" else "."),
                           now, timedelta(hours=settings.autonomy_auto_auth_ttl_hours))
        history.record(db, a, "auto_authorized", actor="system", now=now, data={"basis": basis, "scope_hash": ap.scope_hash, "expires_at": ap.expires_at.isoformat(),
                                                                               "permission_set_by": str(srow.autonomy_permissions_by) if srow.autonomy_permissions_by else None})
    return a


# =============================================================================================================================================
# decide / expire / cancel
# =============================================================================================================================================
def decide(db: Session, a: AgentAction, *, user_id: uuid.UUID, role: Role, approve: bool, reason: str | None = None, now: datetime | None = None) -> AgentAction:
    """A person approves or rejects. Level 3 needs an OWNER; Levels 1-2 an owner or admin. The approval is bound to this exact value and nothing else."""
    now = now or utcnow()
    if a.status == "recommended":
        if approve:
            gloc0, _ = _gloc_conn(db, a)
            gate = v2gate.status_for(gloc0, a.field_key)
            if not gate["allowed"]:
                raise ActionError(gate["reason"], 409)
            a.status, a.expires_at = "pending_approval", now + timedelta(days=settings.autonomy_proposal_ttl_days)  # the gate is open for this profile: it now waits for a person like any other change
            history.record(db, a, "promoted", actor="system", now=now, data={"from": "recommended", "gate": {k: gate[k] for k in ("test_profile", "customer_writes")}})
    elif a.status != "pending_approval":
        raise ActionError(f"This action is {a.status.replace('_', ' ')}, so it cannot be approved or rejected.")
    need = Role.owner if a.policy_level >= 3 else Role.admin
    if ROLE_RANK[role] < ROLE_RANK[need]:
        raise ActionError("Only the business owner can authorise this kind of change." if need == Role.owner else "You do not have permission to do this.", 403)
    if a.expires_at is not None and a.expires_at <= now:
        a.status = "expired"
        history.record(db, a, "expired", actor="system", now=now, data={"was": "pending_approval"})
        db.commit()
        raise ActionError("This proposal expired. Ask for it to be re-evaluated.")
    if not approve:
        if not (reason or "").strip():
            raise ActionError("Say why you are rejecting it (it helps FlowQR avoid proposing it again).", 422)
        _add_approval(db, a, "rejected", "owner" if role == Role.owner else "admin", user_id, reason.strip()[:500], now, None)
        a.status = "rejected"
        history.record(db, a, "rejected", actor="user", user_id=user_id, now=now, data={"reason": reason.strip()[:500]})
        return a
    # approving: it must still be true, today
    tenant, (gloc, _) = db.get(Tenant, a.tenant_id), _gloc_conn(db, a)
    snap = db.scalar(select(GbpSnapshot).where(GbpSnapshot.google_location_id == a.google_location_id))
    live_now = pol.field_value(snap.info if snap else None, a.field_key)
    kb = kbs.context(db, tenant)
    facts_now = pol.facts_fingerprint(a.action_type, a.source, kb, _tenant_facts(tenant), a.proposed_value.get("canonical"))
    why = None
    if snap is None or snap.info is None or pol.fingerprint(live_now) != a.base_fingerprint:
        why = "The Google profile has changed since this was proposed."
    elif facts_now != a.facts_fingerprint:
        why = "The business facts this was based on have changed since it was proposed."
    if why:
        a.status = "invalidated"
        history.record(db, a, "invalidated", actor="system", now=now, data={"reason": why, "at": "approval"})
        db.commit()
        raise ActionError(why + " It needs to be re-evaluated, so nothing was approved.")
    ap = _add_approval(db, a, "approved", "owner" if role == Role.owner else "admin", user_id, (reason or "").strip()[:500] or None, now, timedelta(hours=settings.autonomy_approval_ttl_hours))
    a.status, a.next_attempt_at, a.expires_at = "approved", None, None
    history.record(db, a, "approved", actor="user", user_id=user_id, now=now, data={"basis": ap.basis, "scope": ap.scope, "scope_hash": ap.scope_hash, "expires_at": ap.expires_at.isoformat(),
                                                                                  "reason": ap.reason, "comparison": {"before": a.current_value.get("value"), "after": a.proposed_value.get("canonical")}})
    return a


def approve_now(db: Session, a: AgentAction, *, user_id: uuid.UUID, role: Role, reason: str | None = None, now: datetime | None = None) -> AgentActionApproval:
    """A person who is making the change right now (the profile editor) authorises exactly this action. Same role rule as `decide`: Level 3 needs the owner.
    The action was just judged against the live Google profile, so there is no snapshot to re-check."""
    now = now or utcnow()
    need = Role.owner if a.policy_level >= 3 else Role.admin
    if ROLE_RANK[role] < ROLE_RANK[need]:
        raise ActionError("Only the business owner can make this kind of change." if need == Role.owner else "You do not have permission to do this.", 403)
    ap = _add_approval(db, a, "approved", "owner" if role == Role.owner else "admin", user_id, reason, now, timedelta(hours=settings.autonomy_approval_ttl_hours))
    a.status, a.next_attempt_at, a.expires_at = "approved", None, None
    history.record(db, a, "approved", actor="user", user_id=user_id, now=now, data={"basis": ap.basis, "scope": ap.scope, "scope_hash": ap.scope_hash, "expires_at": ap.expires_at.isoformat(),
                                                                                  "reason": reason, "comparison": {"before": a.current_value.get("value"), "after": a.proposed_value.get("canonical")}})
    return ap


FIELD_TYPES = {"description": "description_improve", "hours": "hours_update", "website": "contact_update", "phone": "contact_update",
               "additional_categories": "secondary_category_update", "primary_category": "primary_category_change"}


def owner_edit(db: Session, tenant: Tenant, gloc: GoogleLocation, *, user_id: uuid.UUID, role: Role, changes: dict, live: dict, provider=None, now: datetime | None = None,
               sleep=None) -> dict:
    """A person edits the Google profile from FlowQR. It goes through the SAME policy, claim, write, read-back and history as every other profile change: one action
    per field, classified by code (a main-category change needs the owner; replacing an existing phone or website, or removing information, is Level 3), judged against
    `live` (what Google holds right now), executed in interactive mode (no background retry: the person is waiting), then confirmed by an independent read.

    Returns {"applied": [fields], "unchanged": [fields], "failed": None | {"field", "status", "detail", "http"}}. Raises ActionError for what is refused before any write
    (platform stop, a role that may not make this change, a value the policy blocks)."""
    now = now or utcnow()
    stop = controls.emergency_stop(db)
    if stop:
        raise ActionError(f"Profile changes are paused for the whole platform ({stop['reason']}). Nothing was changed.", 503)
    out: dict = {"applied": [], "unchanged": [], "failed": None}
    for fk, value in changes.items():
        atype = FIELD_TYPES[fk]
        if pol.canon(fk, value) == pol.field_value(live, fk):
            out["unchanged"].append(fk)
            continue
        a = propose(db, tenant, gloc, atype, field_key=fk if atype == "contact_update" else None, proposed=value, source={"kind": "owner_input", "user_id": str(user_id)},
                    trigger="owner_edit", problem="You changed this on your profile in FlowQR.", reason="You edited it yourself.", proposed_by="user", user_id=user_id, now=now,
                    info_override=live, relaxed=True, force_owner=True)
        if a.status == "blocked":
            db.commit()
            raise ActionError(a.last_error or "That change is not allowed.", 422)
        if a.status == "executing":
            db.commit()
            raise ActionError("This change is already being sent to Google. Wait a moment.", 409)
        if a.status == "pending_approval":
            approve_now(db, a, user_id=user_id, role=role, now=now)
        db.commit()
        r = execute(db, a.id, provider=provider, now=now, sleep=sleep, interactive=True)
        if r.get("status") != "executed":
            out["failed"] = {"field": fk, "status": r.get("status"), "reason": r.get("reason"), "detail": r.get("detail"), "http": r.get("http"), "google_error": r.get("google_error")}
            return out
        out["applied"].append(fk)
    return out


def cancel(db: Session, a: AgentAction, *, user_id: uuid.UUID, now: datetime | None = None) -> AgentAction:
    now = now or utcnow()
    if a.status not in ("pending_approval", "approved"):
        raise ActionError(f"This action is {a.status.replace('_', ' ')} and cannot be cancelled.")
    ap = _valid_approval(db, a)
    if ap is not None:
        ap.invalidated_at, ap.invalidated_reason = now, "cancelled by a person"
    a.status = "canceled"
    history.record(db, a, "canceled", actor="user", user_id=user_id, now=now, data={})
    return a


def expire_due(db: Session, *, now: datetime | None = None) -> dict:
    """Proposals nobody decided on, and authorisations that ran out before the change was made, expire. Nothing expired is ever executed."""
    now = now or utcnow()
    out = {"proposals": 0, "approvals": 0}
    for a in db.scalars(select(AgentAction).where(AgentAction.status == "pending_approval", AgentAction.expires_at <= now).with_for_update(skip_locked=True)):
        a.status = "expired"
        history.record(db, a, "expired", actor="system", now=now, data={"was": "pending_approval"})
        out["proposals"] += 1
    for a in db.scalars(select(AgentAction).where(AgentAction.status == "approved", AgentAction.subject_type.is_(None)).with_for_update(skip_locked=True)):
        ap = _valid_approval(db, a)
        if ap is not None and ap.expires_at is not None and ap.expires_at <= now:
            ap.invalidated_at, ap.invalidated_reason = now, "expired before execution"
            a.status = "expired"
            history.record(db, a, "expired", actor="system", now=now, data={"was": "approved", "approval_expired_at": ap.expires_at.isoformat()})
            out["approvals"] += 1
    db.commit()
    return out


# =============================================================================================================================================
# execute
# =============================================================================================================================================
def _autonomous_in_last_day(db: Session, tenant_id: uuid.UUID, now: datetime) -> int:
    autonomous = select(AgentActionApproval.action_id).where(AgentActionApproval.basis.in_(AUTONOMOUS_BASES), AgentActionApproval.decision == "auto_authorized")
    return db.scalar(select(func.count()).select_from(AgentAction).where(
        AgentAction.tenant_id == tenant_id, AgentAction.status.in_(("executed", "executing")), func.coalesce(AgentAction.executed_at, AgentAction.claimed_at) >= now - timedelta(hours=24),
        AgentAction.id.in_(autonomous))) or 0


def _write_changes(a: AgentAction) -> dict:
    raw = a.proposed_value.get("value")
    return {a.field_key: raw}


def _terminal(db: Session, a: AgentAction, status: str, event: str, data: dict, now: datetime, *, ap: AgentActionApproval | None = None, why: str | None = None) -> dict:
    a.status = status
    if status == "pending_approval":  # sent back to a person: it needs a fresh deadline
        a.expires_at = now + timedelta(days=settings.autonomy_proposal_ttl_days)
    if why:
        a.last_error = why[:1000]
    if ap is not None and status in ("invalidated", "expired"):
        ap.invalidated_at, ap.invalidated_reason = now, (why or event)[:300]
    history.record(db, a, event, actor="system", now=now, data=data)
    db.commit()
    return {"status": status, "reason": event, "detail": why}


def _note_failure(db: Session, a: AgentAction, now: datetime) -> bool:
    """A terminal failed execution counts toward automatic suspension. Returns True if this suspended the business's autonomy."""
    s = get_settings(db, a.tenant_id)
    s.autonomy_failure_streak = (s.autonomy_failure_streak or 0) + 1
    if s.autonomy_failure_streak >= settings.autonomy_failure_suspend and not s.autonomy_suspended_at:
        s.autonomy_suspended_at = now
        s.autonomy_suspended_reason = f"{s.autonomy_failure_streak} executions in a row failed. Autonomy was suspended automatically; nothing runs on its own until an owner resumes it."
        history.record(db, a, "autonomy_suspended", actor="system", now=now, data={"streak": s.autonomy_failure_streak, "reason": s.autonomy_suspended_reason})
        audit(db, action="autonomy.suspended", tenant_id=a.tenant_id, entity_type="agent_settings", entity_id=s.id, meta={"streak": s.autonomy_failure_streak, "action": str(a.id)})
        return True
    return False


def execute(db: Session, action_id: uuid.UUID, *, provider=None, now: datetime | None = None, sleep=None, interactive: bool = False) -> dict:
    """Execute one authorised action, with every check repeated at this moment. Returns {"status": ..., ...}. Idempotent: an executed action is never executed again."""
    now = now or utcnow()
    sleep = sleep or time.sleep
    # populate_existing: whatever this session cached is not trusted; the row is read fresh, under the lock
    a = db.scalar(select(AgentAction).where(AgentAction.id == action_id).with_for_update(skip_locked=True).execution_options(populate_existing=True))
    if a is None:
        return {"status": "skipped", "reason": "missing_or_locked"}
    if a.subject_type is not None:  # a post, photo or reply: governed by content_exec, never written as a profile field
        db.rollback()
        return {"status": a.status, "reason": "not_a_profile_field"}
    if a.status != "approved":
        db.rollback()
        return {"status": a.status, "reason": "not_approved"}
    if a.next_attempt_at is not None and a.next_attempt_at > now:
        db.rollback()
        return {"status": "approved", "reason": "not_due"}
    stop = controls.emergency_stop(db)
    if stop:
        db.rollback()
        return {"status": "held", "reason": "emergency_stop", "detail": stop["reason"]}
    tenant = db.get(Tenant, a.tenant_id)
    gloc, conn = _gloc_conn(db, a)
    gate = v2gate.status_for(gloc, a.field_key)
    if gate["applies"] and not gate["allowed"]:  # approved while the gate was open, and it has closed since: held, never failed, never written
        a.next_attempt_at = now + timedelta(hours=1)
        history.record(db, a, "held", actor="system", now=now, data={"reason": "the customer-write policy gate is closed for this profile"})
        db.commit()
        return {"status": "held", "reason": "policy_gate", "detail": gate["reason"]}
    if tenant is None or gloc is None or conn is None or gloc.tenant_id != a.tenant_id or conn.tenant_id != a.tenant_id:
        return _terminal(db, a, "blocked", "tenant_mismatch", {"reason": "the action, location and Google connection do not all belong to the same business"}, now, why="Tenant ownership could not be verified.")
    if not tenant.is_active or tenant.suspended_at or tenant.deletion_scheduled_for or not gloc.selected or conn.status != GoogleConnectionStatus.active:
        return _terminal(db, a, "canceled", "target_unavailable", {"reason": "the business is inactive or the location is no longer connected"}, now, why="The business or location is no longer available.")
    if not ent.for_tenant(db, tenant.id).has("gbp_info"):
        a.next_attempt_at = now + timedelta(hours=1)
        history.record(db, a, "held", actor="system", now=now, data={"reason": "the plan does not include profile management or is inactive"})
        db.commit()
        return {"status": "held", "reason": "plan"}
    srow = get_settings(db, a.tenant_id)
    ap = _valid_approval(db, a)
    if ap is None or ap.decision == "rejected":
        a.status = "pending_approval"
        return _terminal(db, a, "pending_approval", "authorization_missing", {"reason": "no valid authorisation found"}, now)
    if ap.expires_at is not None and ap.expires_at <= now:
        return _terminal(db, a, "expired", "expired", {"was": "approved", "approval_expired_at": ap.expires_at.isoformat()}, now, ap=ap, why="The authorisation expired before it could be used.")
    if pol.fingerprint(_scope(a)) != ap.scope_hash:
        return _terminal(db, a, "invalidated", "invalidated", {"reason": "the action changed after it was authorised"}, now, ap=ap, why="The action no longer matches what was authorised.")
    autonomous = ap.basis in AUTONOMOUS_BASES
    if autonomous:
        perm = (srow.autonomy_permissions or {}).get(a.effective_type, "auto" if a.policy_level == 1 else "ask")
        consented = consent_svc.has_active(db, a.tenant_id, a.google_location_id, a.effective_type)
        if not srow.autonomy_enabled or srow.autonomy_suspended_at or perm != "auto" or a.policy_level >= 3 or not ent.for_tenant(db, tenant.id).has("autonomy") or not consented:
            ap.invalidated_at, ap.invalidated_reason = now, "autonomy was switched off, suspended, narrowed or its consent was withdrawn before execution"
            return _terminal(db, a, "pending_approval", "autonomy_withdrawn", {"reason": ap.invalidated_reason, "enabled": srow.autonomy_enabled,
                                                                              "suspended": bool(srow.autonomy_suspended_at), "permission": perm, "consent": consented}, now)
        if _autonomous_in_last_day(db, a.tenant_id, now) >= srow.autonomy_daily_limit:
            a.next_attempt_at = now + timedelta(hours=1)
            history.record(db, a, "held", actor="system", now=now, data={"reason": "the daily limit for autonomous changes is reached", "limit": srow.autonomy_daily_limit})
            db.commit()
            return {"status": "held", "reason": "daily_limit"}
    # ---- read the live profile and re-verify the premises
    try:
        provider = provider or g.get_google_provider()
        token = get_access_token(db, conn, provider, gloc=gloc, action="edit_profile")
        live, live_c = field_ops.live_value(provider, token, gloc.google_location_name, a.field_key)
    except Exception as exc:  # noqa: BLE001
        reason, may_retry = describe_failure(exc)
        if isinstance(exc, g.GoogleApiNotApproved):
            note_not_approved(conn, exc)
        if may_retry and not interactive and a.attempts < settings.autonomy_max_attempts:
            a.next_attempt_at = now + timedelta(minutes=5 * 2 ** a.attempts)
            history.record(db, a, "retry_scheduled", actor="google", now=now, data={"stage": "pre-check read", "reason": reason, "next_attempt_at": a.next_attempt_at.isoformat()})
            db.commit()
            return {"status": "approved", "reason": "retry", "detail": reason}
        a.status = "failed"
        a.last_error = reason
        history.record(db, a, "failed", actor="google", now=now, data={"stage": "pre-check read", "reason": reason})
        _note_failure(db, a, now)
        db.commit()
        return {"status": "failed", "reason": "google_read", "detail": reason, "http": getattr(exc, "status", None), "google_error": type(exc).__name__}
    prop_c = a.proposed_value.get("canonical")
    if field_ops.same(a.field_key, live_c, prop_c):
        if a.attempts == 0:
            return _terminal(db, a, "invalidated", "already_applied", {"reason": "Google already shows this value; nothing to change", "live": live_c}, now, ap=ap, why="Google already shows this value.")
        return _finish_verified(db, a, gloc, now, {"field": a.field_key, "expected": prop_c, "actual": live_c, "matched": True, "note": "an earlier attempt had already applied it"}, {"adopted": True})
    if pol.fingerprint(live_c) != a.base_fingerprint:
        return _terminal(db, a, "invalidated", "google_value_changed", {"was": a.current_value.get("value"), "now": live_c}, now, ap=ap, why="The value on Google changed after this was proposed.")
    kb = kbs.context(db, tenant)
    facts_now = pol.facts_fingerprint(a.action_type, a.source, kb, _tenant_facts(tenant), prop_c)
    if facts_now != ap.scope.get("facts_fingerprint"):
        return _terminal(db, a, "invalidated", "facts_changed", {"reason": "the verified business facts this relied on have changed"}, now, ap=ap, why="The business facts this was based on have changed.")
    d2 = pol.classify(a.action_type, field_key=a.field_key, current=live_c, proposed=prop_c, kb=kb)
    if d2.level > a.policy_level:
        return _terminal(db, a, "invalidated", "policy_level_increased", {"was": a.policy_level, "now": d2.level, "reasons": d2.reasons}, now, ap=ap, why="The policy now classifies this at a higher level.")
    problems = pol.validate_proposal(a.action_type, field_key=a.field_key, current=live_c, proposed=prop_c, source=a.source, proposed_by=a.proposed_by, kb=kb, tenant_facts=_tenant_facts(tenant),
                                     info=live)
    if problems or not d2.writable:
        return _terminal(db, a, "invalidated", "evidence_no_longer_sufficient", {"problems": problems or ["not writable through the Google integration"]}, now, ap=ap, why="; ".join(problems) or "Not writable.")
    # ---- the dry run (V2 fields): Google's own validation of exactly what would be sent, before anything is claimed or written
    if a.field_key in pol.V2_FIELDS:
        try:
            vres = field_ops.validate(provider, token, gloc.google_location_name, a.field_key, prop_c, live=live, current=live_c)
        except Exception as exc:  # noqa: BLE001 - a transport or quota problem is not Google's verdict on the value
            reason, may_retry = describe_failure(exc)
            if isinstance(exc, g.GoogleApiNotApproved):
                note_not_approved(conn, exc)
            if may_retry and not interactive and a.attempts < settings.autonomy_max_attempts:
                a.next_attempt_at = now + timedelta(minutes=5 * 2 ** a.attempts)
                history.record(db, a, "retry_scheduled", actor="google", now=now, data={"stage": "validation", "reason": reason, "next_attempt_at": a.next_attempt_at.isoformat()})
                db.commit()
                return {"status": "approved", "reason": "retry", "detail": reason}
            a.status, a.last_error = "failed", reason
            history.record(db, a, "failed", actor="google", now=now, data={"stage": "validation", "reason": reason})
            db.commit()
            return {"status": "failed", "reason": "validation_error", "detail": reason, "http": getattr(exc, "status", None), "google_error": type(exc).__name__}
        a.validation_status, a.validation = vres["status"], {**vres, "at": now.isoformat()}
        history.record(db, a, "validated" if vres["status"] == "validated" else "validation_failed", actor="google", now=now, data=a.validation)
        if vres["status"] != "validated":  # rejected, or no way to dry-run: a V2 write is never sent unvalidated
            why = "; ".join(vres["errors"]) or vres["detail"]
            return _terminal(db, a, "blocked", "validation_failed", {"errors": vres["errors"], "detail": vres["detail"]}, now, ap=ap, why=why)
        db.commit()
    if not hit(f"gbp-edit:{gloc.id}", 10, 60):  # Google allows 10 profile edits per minute per location
        a.next_attempt_at = now + timedelta(seconds=65)
        db.commit()
        return {"status": "approved", "reason": "rate_limited"}
    # ---- baseline ranking, then claim
    spec = pol.SPECS[a.action_type]
    if spec.rank_relevant and a.baseline is None:
        learning.measure_baseline(db, a, gloc, now)
    a.status, a.attempts, a.claimed_at, a.last_error = "executing", a.attempts + 1, now, None
    try:
        history.record(db, a, "executing", actor="system", now=now, data={"attempt": a.attempts, "basis": ap.basis})  # flushes: the in-flight unique index is enforced here
        db.commit()  # the atomic claim, durable before Google is touched
    except IntegrityError:  # another action is already writing this field of this location
        db.rollback()
        a = db.get(AgentAction, action_id)
        a.next_attempt_at = now + timedelta(seconds=60)
        db.commit()
        return {"status": "approved", "reason": "location_field_busy"}
    # ---- write
    try:
        result = field_ops.write(provider, token, gloc.google_location_name, a.field_key, a.proposed_value.get("value"), prop_c, current=live_c)
    except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
        api_usage.record(db, tenant_id=a.tenant_id, provider=api_usage.GBP, operation="locations.patch", feature="autonomy", status="error", location_id=a.google_location_id,
                         idempotency_key=f"gbp:{a.id}:{a.attempts}", reason=type(exc).__name__)
        reason, may_retry = describe_failure(exc)
        if isinstance(exc, g.GoogleApiNotApproved):
            note_not_approved(conn, exc)
        if may_retry and not interactive and a.attempts < settings.autonomy_max_attempts:
            a.status, a.next_attempt_at, a.last_error = "approved", now + timedelta(minutes=5 * 2 ** (a.attempts - 1)), reason
            history.record(db, a, "retry_scheduled", actor="google", now=now, data={"reason": reason, "attempt": a.attempts, "next_attempt_at": a.next_attempt_at.isoformat()})
            db.commit()
            return {"status": "approved", "reason": "retry", "detail": reason}
        a.status, a.last_error = "failed", reason
        history.record(db, a, "failed", actor="google", now=now, data={"stage": "write", "reason": reason, "attempt": a.attempts})
        _note_failure(db, a, now)
        db.commit()
        return {"status": "failed", "reason": "write", "detail": reason, "http": getattr(exc, "status", None), "google_error": type(exc).__name__}
    api_usage.record(db, tenant_id=a.tenant_id, provider=api_usage.GBP, operation="locations.patch", feature="autonomy", location_id=a.google_location_id, idempotency_key=f"gbp:{a.id}:{a.attempts}")
    history.record(db, a, "google_write", actor="google", now=now, data={"field": a.field_key, "requested": prop_c, "returned": field_ops.returned_value(result, a.field_key)})
    # ---- read back, independently, and compare
    sleep(0)
    try:
        _, actual = field_ops.live_value(provider, token, gloc.google_location_name, a.field_key)
    except Exception as exc:  # noqa: BLE001 - the write may or may not have landed: leave it for recovery to resolve, do not claim success
        reason, _ = describe_failure(exc)
        history.record(db, a, "read_back_failed", actor="google", now=now, data={"reason": reason})
        db.commit()
        return {"status": "executing", "reason": "read_back_failed", "detail": reason}
    matched = field_ops.same(a.field_key, actual, prop_c)
    ver = {"field": a.field_key, "expected": prop_c, "actual": actual, "matched": matched, "read_at": utcnow().isoformat()}
    if not matched:
        a.status, a.verification = "failed", ver
        a.last_error = f"Google accepted the request but its profile does not show the new {a.field_key} yet."
        history.record(db, a, "read_back", actor="google", now=now, data=ver)
        history.record(db, a, "failed", actor="google", now=now, data={"stage": "verification", "reason": a.last_error})
        _note_failure(db, a, now)
        db.commit()
        return {"status": "failed", "reason": "read_back_mismatch", "detail": a.last_error}
    return _finish_verified(db, a, gloc, now, ver, {"accepted": True})


def _finish_verified(db: Session, a: AgentAction, gloc: GoogleLocation, now: datetime, verification: dict, google_result: dict) -> dict:
    a.status, a.executed_at, a.verified_at, a.verification, a.google_result, a.last_error = "executed", now, now, verification, google_result, None
    history.record(db, a, "read_back", actor="google", now=now, data=verification)
    history.record(db, a, "verified", actor="system", now=now, data={"field": a.field_key, "matched": True})
    s = get_settings(db, a.tenant_id)
    s.autonomy_failure_streak = 0
    if pol.SPECS[a.action_type].rank_relevant:
        learning.schedule_followups(db, a, now)
    if a.field_key in pol.V2_FIELDS:  # a customer-visible V2 change: the separate notice, only now that Google's own profile shows it
        from app.services.agent.v2 import notice

        notice.send_change_notice(db, a)
    db.commit()
    return {"status": "executed", "verified": True}


def withdraw_autonomous(db: Session, tenant_id: uuid.UUID, *, reason: str, user_id: uuid.UUID | None = None, now: datetime | None = None,
                        google_location_id: uuid.UUID | None = None, effective_type: str | None = None) -> int:
    """Return every action that was authorised by standing policy (not by a named person) to "waiting for a person", right now. Used by the owner's emergency stop so
    nothing waits for the next job run to be withdrawn. Person-approved actions are untouched: a person decided those."""
    now = now or utcnow()
    n = 0
    q = select(AgentAction).where(AgentAction.tenant_id == tenant_id, AgentAction.status == "approved", AgentAction.subject_type.is_(None))
    if google_location_id is not None:  # withdrawing ONE consent: only that location's, and that action type's, queued work
        q = q.where(AgentAction.google_location_id == google_location_id)
    if effective_type is not None:
        q = q.where(AgentAction.effective_type == effective_type)
    for a in db.scalars(q.with_for_update(skip_locked=True)):
        ap = _valid_approval(db, a)
        if ap is not None and ap.basis in AUTONOMOUS_BASES:
            ap.invalidated_at, ap.invalidated_reason = now, reason[:300]
            a.status, a.expires_at = "pending_approval", now + timedelta(days=settings.autonomy_proposal_ttl_days)
            history.record(db, a, "autonomy_withdrawn", actor="user" if user_id else "system", user_id=user_id, now=now, data={"reason": reason})
            n += 1
    return n


def run_due(db: Session, *, provider=None, now: datetime | None = None, limit: int = 10) -> dict:
    """The scheduled job: execute what is approved and due. Held (not failed) while the platform emergency stop is on."""
    now = now or utcnow()
    stop = controls.emergency_stop(db)
    if stop:
        return {"stopped": True, "reason": stop["reason"], "executed": 0}
    ids = list(db.scalars(select(AgentAction.id).where(AgentAction.status == "approved", AgentAction.subject_type.is_(None), (AgentAction.next_attempt_at.is_(None)) | (AgentAction.next_attempt_at <= now))
                          .order_by(AgentAction.created_at).limit(limit)))
    out: dict = {"stopped": False}
    for aid in ids:
        try:
            r = execute(db, aid, provider=provider, now=now)
        except Exception:  # noqa: BLE001 - one action must not stop the others; it stays approved and is retried
            db.rollback()
            log.exception("autonomy execution crashed for action %s", aid)
            r = {"status": "error"}
        out[r["status"]] = out.get(r["status"], 0) + 1
    return out


def recover_stuck(db: Session, *, provider=None, now: datetime | None = None, limit: int = 20) -> dict:
    """Actions left `executing` by a crash: ask Google what is there. Matching -> verified; not matching -> back to approved (every check runs again before any new
    write); cannot ask -> left alone. Never writes."""
    now = now or utcnow()
    out = {"verified": 0, "requeued": 0, "failed": 0, "deferred": 0}
    ids = list(db.scalars(select(AgentAction.id).where(AgentAction.status == "executing", AgentAction.subject_type.is_(None),
                                                       AgentAction.claimed_at < now - timedelta(minutes=settings.autonomy_stuck_minutes)).limit(limit)))
    for aid in ids:
        a = db.scalar(select(AgentAction).where(AgentAction.id == aid, AgentAction.status == "executing").with_for_update(skip_locked=True))
        if a is None:
            continue
        gloc, conn = _gloc_conn(db, a)
        try:
            provider = provider or g.get_google_provider()
            _, actual = field_ops.live_value(provider, get_access_token(db, conn, provider, gloc=gloc), gloc.google_location_name, a.field_key)
        except Exception as exc:  # noqa: BLE001
            log.warning("autonomy recovery could not read Google for %s: %s", aid, exc)
            out["deferred"] += 1
            db.rollback()
            continue
        if field_ops.same(a.field_key, actual, a.proposed_value.get("canonical")):
            ver = {"field": a.field_key, "expected": actual, "actual": actual, "matched": True, "note": "found applied on Google when recovering from an interruption"}
            _finish_verified(db, a, gloc, now, ver, {"recovered": True})
            out["verified"] += 1
        elif a.attempts >= settings.autonomy_max_attempts:
            a.status, a.last_error = "failed", "Interrupted while executing and not applied on Google after several attempts."
            history.record(db, a, "failed", actor="system", now=now, data={"stage": "recovery", "reason": a.last_error})
            _note_failure(db, a, now)
            db.commit()
            out["failed"] += 1
        else:
            a.status, a.next_attempt_at = "approved", now
            history.record(db, a, "recovered_requeued", actor="system", now=now, data={"reason": "interrupted before Google applied it; every check will run again before any write"})
            db.commit()
            out["requeued"] += 1
    return out


# =============================================================================================================================================
# presentation
# =============================================================================================================================================
def action_out(db: Session, a: AgentAction, *, detail: bool = False) -> dict:
    out = {
        "id": str(a.id), "google_location_id": str(a.google_location_id), "action_type": a.action_type, "effective_type": a.effective_type, "label": pol.SPECS[a.action_type].label,
        "field": a.field_key, "status": a.status, "policy_level": a.policy_level, "policy": pol.LABELS[a.policy_level], "risk": a.risk_level, "authorization": a.authorization,
        "trigger": a.trigger, "problem": a.problem, "reason": a.reason, "expected_outcome": a.expected_outcome,
        "before": a.current_value.get("value"), "after": a.proposed_value.get("canonical"), "source": a.source, "evidence": a.evidence, "policy_reasons": a.policy_reasons,
        "proposed_by": a.proposed_by, "expires_at": a.expires_at, "attempts": a.attempts, "last_error": a.last_error, "executed_at": a.executed_at, "verified_at": a.verified_at,
        "verification": a.verification, "created_at": a.created_at, "validation_status": a.validation_status, "v2": a.field_key in pol.V2_FIELDS,
    }
    if a.field_key in pol.V2_FIELDS:  # lists of objects are shown to a person as plain lines (what is added, what is removed), never as raw JSON
        out["diff"] = present.describe(a.field_key, out["before"], out["after"], a.evidence)
    if detail:
        out["proposed_raw"] = a.proposed_value.get("value")
        out["baseline"], out["outcome"], out["google_result"], out["validation"] = a.baseline, a.outcome, a.google_result, a.validation
        out["approvals"] = [{"decision": p.decision, "basis": p.basis, "by": str(p.authorized_by) if p.authorized_by else None, "at": p.decided_at, "expires_at": p.expires_at,
                             "reason": p.reason, "invalidated_at": p.invalidated_at, "invalidated_reason": p.invalidated_reason}
                            for p in db.scalars(select(AgentActionApproval).where(AgentActionApproval.action_id == a.id).order_by(AgentActionApproval.decided_at))]
        out["history"] = history.timeline(db, a.id)
        out["history_integrity"] = history.verify(db, a.id)
    return out
