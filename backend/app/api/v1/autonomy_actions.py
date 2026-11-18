"""Balanced Autonomy API: the actions FlowQR proposes for your Google profile, how they are authorised, and the controls over autonomy.

Who may do what: anyone who can see a location can read its actions; owners and admins propose, approve (Level 1-2), reject and cancel; ONLY THE OWNER approves a
Level 3 action, turns autonomy on, changes what is pre-authorised or resumes a suspended business; only a platform admin can use the emergency stop.
No request field carries a policy level: the level is computed by the server from the action type and the values (a request that tries to send one is refused)."""
import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.deps import AuthContext, TenantContext, get_tenant_context, require_platform_admin, require_role
from app.core.rate_limit import client_ip, hit
from app.models import AgentAction, ConsentGrant, GoogleLocation, Role
from app.models.base import utcnow
from app.services import consent as consent_svc
from app.services import entitlements as ent
from app.services.agent import autonomy_policy as pol
from app.services.agent import controls, executor, history, seo_engine
from app.services.audit import audit

router = APIRouter(tags=["autonomy"])


def _gloc(ctx: TenantContext, gid: uuid.UUID) -> GoogleLocation:
    gl = ctx.db.scalar(select(GoogleLocation).where(GoogleLocation.id == gid, GoogleLocation.tenant_id == ctx.tenant_id))
    if gl is None or not gl.selected or not ctx.can_access_location(gl.location_id):
        raise HTTPException(status_code=404, detail="Google location not found")
    return gl


def _action(ctx: TenantContext, aid: uuid.UUID) -> AgentAction:
    a = ctx.db.scalar(select(AgentAction).where(AgentAction.id == aid, AgentAction.tenant_id == ctx.tenant_id))
    gl = ctx.db.get(GoogleLocation, a.google_location_id) if a else None
    if a is None or gl is None or not ctx.can_access_location(gl.location_id):
        raise HTTPException(status_code=404, detail="Action not found")
    return a


def _err(exc: Exception):
    if isinstance(exc, executor.ActionError):
        return HTTPException(status_code=exc.status, detail=str(exc))
    if isinstance(exc, pol.PolicyError):
        return HTTPException(status_code=422, detail=str(exc))
    raise exc


# ---------------------------------------------------------------------------------------------------------------------------------------------
# the policy, transparently
# ---------------------------------------------------------------------------------------------------------------------------------------------
@router.get("/agent/policy")
def policy_table(ctx: TenantContext = Depends(get_tenant_context)):
    """What FlowQR may do on its own, what it needs your pre-authorisation for, and what is always yours. Served from the same table the code enforces."""
    return {"levels": pol.LABELS, "actions": [{"type": s.key, "label": s.label, "level": s.level, "level_label": pol.LABELS[s.level], "writes_to_google": not s.internal,
                                               "supported_by_google_integration": s.writable, "can_be_preauthorised": s.level < 3 and not s.internal and not s.person_only, "needs_person_every_time": s.person_only or s.level >= 3}
                                              for s in pol.SPECS.values()],
            "rules": ["The level is decided by the server from the action type and the values being changed; it can only go UP, never down.",
                      "Level 3 changes always need the owner and can never be pre-authorised.",
                      "A change without verified evidence from your business knowledge, your business record or your own input is blocked, not guessed.",
                      "Every action is re-checked at the moment it runs, and counts as done only when Google's own profile shows the new value.",
                      "Nothing here promises a ranking. Rankings are measured afterwards and reported as observed, never as caused by a change."]}


# ---------------------------------------------------------------------------------------------------------------------------------------------
# actions
# ---------------------------------------------------------------------------------------------------------------------------------------------
@router.get("/agent/actions")
def list_actions(status: str | None = Query(None), limit: int = Query(50, ge=1, le=200), ctx: TenantContext = Depends(get_tenant_context)):
    q = select(AgentAction).join(GoogleLocation, GoogleLocation.id == AgentAction.google_location_id).where(AgentAction.tenant_id == ctx.tenant_id, ctx.scope(GoogleLocation.location_id))
    if status:
        q = q.where(AgentAction.status == status)
    rows = ctx.db.scalars(q.order_by(AgentAction.created_at.desc()).limit(limit)).all()
    out = [executor.action_out(ctx.db, a) for a in rows]
    ctx.db.commit()
    return {"actions": out}


@router.get("/agent/actions/{action_id}")
def get_action(action_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    out = executor.action_out(ctx.db, _action(ctx, action_id), detail=True)
    ctx.db.commit()
    return out


class ProposeIn(BaseModel):
    """What a person may ask for. `extra="forbid"`: there is no `level`, `authorization` or `status` to send, and sending one is a 422."""

    model_config = ConfigDict(extra="forbid")
    google_location_id: uuid.UUID
    action_type: str = Field(min_length=3, max_length=40)
    field: str | None = Field(default=None, max_length=40)
    proposed: Any
    source_kind: str = Field(default="owner_input", max_length=24)
    source_refs: list[str] = Field(default_factory=list, max_length=8)
    problem: str = Field(min_length=3, max_length=500)
    reason: str = Field(min_length=3, max_length=1000)


@router.post("/agent/actions", status_code=201)
def propose_action(body: ProposeIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Ask FlowQR to make one change. It is classified, checked against verified facts and then either waits for a person, is authorised by your standing
    pre-authorisation for that exact type, or is blocked with the reason."""
    ent.require_feature(ctx.db, ctx.tenant_id, "autonomy")
    gl = _gloc(ctx, body.google_location_id)
    source = {"kind": body.source_kind, "refs": body.source_refs, **({"user_id": str(ctx.user.id)} if body.source_kind == "owner_input" else {})}
    try:
        a = executor.propose(ctx.db, ctx.tenant, gl, body.action_type, field_key=body.field, proposed=body.proposed, source=source, trigger="owner_request", problem=body.problem,
                             reason=body.reason, proposed_by="user", user_id=ctx.user.id)
    except (pol.PolicyError, executor.ActionError) as exc:
        raise _err(exc)
    audit(ctx.db, action="autonomy.propose", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="agent_action", entity_id=a.id,
          meta={"type": a.action_type, "level": a.policy_level, "status": a.status}, ip=client_ip(request))
    out = executor.action_out(ctx.db, a, detail=True)
    ctx.db.commit()
    return out


class DecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=500)


@router.post("/agent/actions/{action_id}/approve")
def approve_action(action_id: uuid.UUID, body: DecisionIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Approve exactly this action and this value (Level 3: owner only), then run it now. The result is Google's, verified by reading the profile back."""
    ent.require_feature(ctx.db, ctx.tenant_id, "autonomy")
    a = _action(ctx, action_id)
    try:
        executor.decide(ctx.db, a, user_id=ctx.user.id, role=ctx.role, approve=True, reason=body.reason)
    except executor.ActionError as exc:
        ctx.db.commit()  # an invalidation or expiry found while deciding stays on record
        raise _err(exc)
    audit(ctx.db, action="autonomy.approve", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="agent_action", entity_id=a.id, meta={"level": a.policy_level}, ip=client_ip(request))
    ctx.db.commit()
    result = executor.execute(ctx.db, a.id)
    ctx.db.refresh(a)
    out = executor.action_out(ctx.db, a, detail=True)
    ctx.db.commit()
    return {**out, "execution": result}


class RejectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=3, max_length=500)


@router.post("/agent/actions/{action_id}/reject")
def reject_action(action_id: uuid.UUID, body: RejectIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    a = _action(ctx, action_id)
    try:
        executor.decide(ctx.db, a, user_id=ctx.user.id, role=ctx.role, approve=False, reason=body.reason)
    except executor.ActionError as exc:
        raise _err(exc)
    audit(ctx.db, action="autonomy.reject", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="agent_action", entity_id=a.id, meta={"reason": body.reason}, ip=client_ip(request))
    out = executor.action_out(ctx.db, a, detail=True)
    ctx.db.commit()
    return out


@router.post("/agent/actions/{action_id}/cancel")
def cancel_action(action_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    a = _action(ctx, action_id)
    try:
        executor.cancel(ctx.db, a, user_id=ctx.user.id)
    except executor.ActionError as exc:
        raise _err(exc)
    audit(ctx.db, action="autonomy.cancel", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="agent_action", entity_id=a.id, ip=client_ip(request))
    out = executor.action_out(ctx.db, a)
    ctx.db.commit()
    return out


@router.post("/agent/actions/scan")
def scan_now(request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Look for verified improvements now (may use one AI draft per location, within your AI budget). Proposals only: nothing is written to Google by this call."""
    ent.require_feature(ctx.db, ctx.tenant_id, "autonomy")
    if not hit(f"autonomy-scan:{ctx.tenant_id}", 4, 3600):
        raise HTTPException(status_code=429, detail="Scanning is limited to a few times an hour.")
    out = seo_engine.scan_tenant(ctx.db, ctx.tenant)
    audit(ctx.db, action="autonomy.scan", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="tenant", entity_id=ctx.tenant_id, meta={"proposed": out["proposed"]}, ip=client_ip(request))
    ctx.db.commit()
    return out


# ---------------------------------------------------------------------------------------------------------------------------------------------
# autonomy settings (the owner's switch)
# ---------------------------------------------------------------------------------------------------------------------------------------------
def _settings_out(ctx: TenantContext, s) -> dict:
    stop = controls.emergency_stop(ctx.db)
    perms = s.autonomy_permissions or {}
    return {"enabled": s.autonomy_enabled, "suspended": bool(s.autonomy_suspended_at), "suspended_at": s.autonomy_suspended_at, "suspended_reason": s.autonomy_suspended_reason,
            "failure_streak": s.autonomy_failure_streak, "daily_limit": s.autonomy_daily_limit, "permissions_set_at": s.autonomy_permissions_at,
            "permissions": [{"type": sp.key, "label": sp.label, "level": sp.level, "mode": perms.get(sp.key, "auto" if sp.level == 1 else "ask"),
                             "can_be_auto": sp.level < 3 and sp.writable and not sp.person_only} for sp in pol.SPECS.values() if not sp.internal],
            "executing_now": bool(s.autonomy_enabled and not s.autonomy_suspended_at and not stop),
            "platform_emergency_stop": bool(stop), "platform_emergency_stop_reason": (stop or {}).get("reason"),
            "note": "Autonomy is off until the owner turns it on. Level 3 changes always need the owner; Level 2 changes only run on their own where the owner set that exact type to 'auto'."}


@router.get("/agent/autonomy-settings")
def get_autonomy_settings(ctx: TenantContext = Depends(get_tenant_context)):
    ent.require_feature(ctx.db, ctx.tenant_id, "autonomy")
    s = executor.get_settings(ctx.db, ctx.tenant_id)
    out = _settings_out(ctx, s)
    ctx.db.commit()
    return out


class AutonomySettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool | None = None
    permissions: dict[str, str] | None = None
    daily_limit: int | None = Field(default=None, ge=0, le=50)


@router.put("/agent/autonomy-settings")
def put_autonomy_settings(body: AutonomySettingsIn, request: Request, ctx: TenantContext = Depends(require_role(Role.owner))):
    """Owner only. Switching autonomy off takes effect immediately: pending autonomous actions are returned to 'waiting for you' before they can run."""
    if body.enabled or body.permissions:  # switching OFF always works; switching on or granting permissions needs the plan feature
        ent.require_feature(ctx.db, ctx.tenant_id, "autonomy")
    s = executor.get_settings(ctx.db, ctx.tenant_id)
    changes: dict = {}
    if body.permissions is not None:
        bad = pol.validate_permissions(body.permissions)
        if bad:
            raise HTTPException(status_code=422, detail={"code": "invalid_permissions", "problems": bad})
        s.autonomy_permissions = {**(s.autonomy_permissions or {}), **body.permissions}
        s.autonomy_permissions_by, s.autonomy_permissions_at = ctx.user.id, utcnow()
        changes["permissions"] = body.permissions
    if body.enabled is not None:
        s.autonomy_enabled = body.enabled
        changes["enabled"] = body.enabled
    if body.daily_limit is not None:
        s.autonomy_daily_limit = body.daily_limit
        changes["daily_limit"] = body.daily_limit
    audit(ctx.db, action="autonomy.settings", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="agent_settings", entity_id=s.id, meta=changes, ip=client_ip(request))
    out = _settings_out(ctx, s)
    ctx.db.commit()
    return out


@router.post("/agent/autonomy-settings/resume")
def resume_autonomy(request: Request, ctx: TenantContext = Depends(require_role(Role.owner))):
    s = executor.get_settings(ctx.db, ctx.tenant_id)
    s.autonomy_suspended_at, s.autonomy_suspended_reason, s.autonomy_failure_streak = None, None, 0
    audit(ctx.db, action="autonomy.resumed", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="agent_settings", entity_id=s.id, ip=client_ip(request))
    out = _settings_out(ctx, s)
    ctx.db.commit()
    return out


# ---------------------------------------------------------------------------------------------------------------------------------------------
# consent: express, per location, per action type, revocable (decision D2)
# ---------------------------------------------------------------------------------------------------------------------------------------------
class ConsentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    location_id: uuid.UUID  # the Google location (the same id the other /agent endpoints use)
    scope: str = Field(min_length=1, max_length=40)
    wording_version: str = Field(min_length=1, max_length=24)  # the version of the wording the owner was shown


class RevokeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str | None = Field(default=None, max_length=300)


class RevokeAllIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    location_id: uuid.UUID | None = None  # omitted = every location of this business
    reason: str | None = Field(default=None, max_length=300)


def _consent_err(exc: consent_svc.ConsentError):
    return HTTPException(status_code=exc.status, detail=str(exc))


@router.get("/agent/consents")
def list_consents(location_id: uuid.UUID | None = None, ctx: TenantContext = Depends(get_tenant_context)):
    """What FlowQR may be allowed to do on its own, the exact wording the owner would agree to, and the full history of consent (active and withdrawn) for the locations the caller can see.
    Nothing is on by default: an empty list means FlowQR will not act on its own anywhere."""
    glocs = {g.id: g for g in ctx.db.scalars(select(GoogleLocation).where(GoogleLocation.tenant_id == ctx.tenant_id, GoogleLocation.selected.is_(True)))
             if ctx.can_access_location(g.location_id) and (location_id is None or g.id == location_id)}
    if location_id is not None and not glocs:
        raise HTTPException(status_code=404, detail="Google location not found")
    rows = list(ctx.db.scalars(select(ConsentGrant).where(ConsentGrant.tenant_id == ctx.tenant_id, ConsentGrant.google_location_id.in_(list(glocs) or [uuid.uuid4()]))
                               .order_by(ConsentGrant.granted_at.desc())))
    return {"wording_version": consent_svc.WORDING_VERSION, "default": "none: automation only runs where an owner has agreed, for that location and that kind of change",
            "scopes": [{k: v for k, v in sc.items()} for sc in consent_svc.scopes().values()],
            "locations": [{"id": str(g.id), "title": g.title} for g in glocs.values()],
            "grants": [consent_svc.out(r) for r in rows], "never_grantable": "Changes to the business name, address, primary category, service area or primary contact details, "
                                                                             "and publishing posts, photos or AI-written replies, are approved by a person every time."}


@router.post("/agent/consents", status_code=201)
def give_consent(body: ConsentIn, request: Request, ctx: TenantContext = Depends(require_role(Role.owner))):
    """Owner only. Records express consent for ONE action type at ONE location, with the exact wording shown. Refuses Level 3 and public-content scopes."""
    ent.require_feature(ctx.db, ctx.tenant_id, "autonomy")
    gl = _gloc(ctx, body.location_id)
    try:
        row, created = consent_svc.grant(ctx.db, tenant_id=ctx.tenant_id, gloc=gl, scope=body.scope, user_id=ctx.user.id, wording_version=body.wording_version, ip=client_ip(request))
    except consent_svc.ConsentError as exc:
        raise _consent_err(exc)
    ctx.db.commit()
    return {**consent_svc.out(row), "created": created}


@router.post("/agent/consents/{consent_id}/revoke")
def withdraw_consent(consent_id: uuid.UUID, body: RevokeIn, request: Request, ctx: TenantContext = Depends(require_role(Role.owner))):
    """Owner only; works at any time, on any plan. Takes effect immediately: queued autonomous work under this grant returns to 'waiting for you'."""
    row = ctx.db.scalar(select(ConsentGrant).where(ConsentGrant.id == consent_id, ConsentGrant.tenant_id == ctx.tenant_id))
    gl = ctx.db.get(GoogleLocation, row.google_location_id) if row else None
    if row is None or gl is None or not ctx.can_access_location(gl.location_id):
        raise HTTPException(status_code=404, detail="Consent not found")
    res = consent_svc.revoke(ctx.db, row, user_id=ctx.user.id, reason=body.reason, ip=client_ip(request))
    ctx.db.commit()
    return {**consent_svc.out(row), **res}


@router.post("/agent/consents/revoke-all")
def withdraw_all_consent(body: RevokeAllIn, request: Request, ctx: TenantContext = Depends(require_role(Role.owner))):
    if body.location_id is not None:
        _gloc(ctx, body.location_id)
    res = consent_svc.revoke_all(ctx.db, ctx.tenant_id, user_id=ctx.user.id, google_location_id=body.location_id, reason=body.reason, ip=client_ip(request))
    audit(ctx.db, action="consent.revoked_all", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="consent_grant", ip=client_ip(request),
          meta={"location_id": str(body.location_id) if body.location_id else None, **res})
    ctx.db.commit()
    return res


# ---------------------------------------------------------------------------------------------------------------------------------------------
# platform emergency stop
# ---------------------------------------------------------------------------------------------------------------------------------------------
class StopIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    on: bool
    reason: str | None = Field(default=None, max_length=300)


@router.get("/admin/autonomy/emergency-stop")
def get_emergency_stop(ctx: AuthContext = Depends(require_platform_admin)):
    return {"stop": controls.emergency_stop(ctx.db)}


@router.put("/admin/autonomy/emergency-stop")
def put_emergency_stop(body: StopIn, ctx: AuthContext = Depends(require_platform_admin)):
    """Stop (or resume) ALL autonomous and approved profile writes, and hold the scheduled post/photo publishers and reply retries, platform-wide. Held work waits."""
    if body.on and not (body.reason or "").strip():
        raise HTTPException(status_code=422, detail="Say why you are stopping execution: it is recorded.")
    out = controls.set_emergency_stop(ctx.db, on=body.on, user_id=ctx.user.id, reason=body.reason)
    ctx.db.commit()
    return {"stop": out}


# ---------------------------------------------------------------------------------------------------------------------------------------------
# the owner's control centre: one read for the whole screen, and the owner's own emergency stop
# ---------------------------------------------------------------------------------------------------------------------------------------------
def _usage(ctx: TenantContext) -> dict:
    from app.core.config import settings
    from app.models import Tenant
    from app.services import ai_usage, rank_grid
    from app.services import usage as usage_svc
    from app.services import rank as rank_svc

    e = ent.for_tenant(ctx.db, ctx.tenant_id)
    tenant = ctx.db.get(Tenant, ctx.tenant_id)
    spend = ai_usage.spend_this_month(ctx.tenant_id)
    budget_usd = float(tenant.ai_monthly_budget_usd) if tenant.ai_monthly_budget_usd is not None else (settings.ai_tenant_monthly_budget_usd or None)
    tok_budget = settings.ai_tenant_monthly_token_budget or None
    gen_used = ai_usage.usage_this_month(ctx.db, ctx.tenant_id)
    allow = rank_grid.allowance(ctx.db, ctx.tenant_id)
    price = settings.rank_cost_per_call_usd
    singles = rank_svc.usage(ctx.db, ctx.tenant_id)
    return {
        "month_resets_on": rank_svc.next_month_start().date().isoformat(),
        "ai": {"generations_used": gen_used, "generations_cap": e.monthly_ai_generations, "review_generations_used": ai_usage.usage_this_month(ctx.db, ctx.tenant_id, "review_generations"),
               "review_generations_cap": e.review_generations, "review_replies_used": ai_usage.usage_this_month(ctx.db, ctx.tenant_id, "review_replies"), "review_replies_cap": e.review_replies, "usd_spent": float(spend["usd"]) if ai_usage.price_known() else None, "usd_budget": budget_usd,
               "tokens_used": spend["tokens"], "tokens_budget": tok_budget, "priced": ai_usage.price_known(), "calls": spend["calls"],
               "note": "Cost is shown only when AI prices are configured on the server; until then calls and tokens are counted but not priced." if not ai_usage.price_known() else None,
               "blocked": bool((budget_usd and float(spend["usd"]) >= budget_usd) or (tok_budget and spend["tokens"] >= tok_budget))},
        "places": {"search_checks_used": singles["used"], "search_checks_cap": singles["cap"], "grid_points_used": allow["used"], "grid_points_cap": allow["cap"],
                   "grid_points_left": allow["remaining"], "grid_enabled": allow["enabled"], "grid_reason": allow.get("reason"),
                   "business_cap": usage_svc.tenant_places_cap(ctx.db, ctx.tenant_id), "units_this_month": usage_svc.units_this_month(ctx.db, ctx.tenant_id), "platform_capped": allow["platform_capped"],
                   "estimated_usd": round((singles["used"] + allow["used"]) * price, 2) if price > 0 else None, "priced": price > 0},
        "autonomy": {"daily_limit": executor.get_settings(ctx.db, ctx.tenant_id).autonomy_daily_limit,
                     "executed_last_24h": executor._autonomous_in_last_day(ctx.db, ctx.tenant_id, utcnow())},
    }


@router.get("/agent/control-centre")
def control_centre(ctx: TenantContext = Depends(get_tenant_context)):
    """Everything the Autonomy control centre shows, in one read: the switch and permissions, what waits for a person, what ran, what failed and why, and this month's
    AI and Google usage against its limits."""
    ent.require_feature(ctx.db, ctx.tenant_id, "autonomy")
    s = executor.get_settings(ctx.db, ctx.tenant_id)
    base = select(AgentAction).join(GoogleLocation, GoogleLocation.id == AgentAction.google_location_id).where(AgentAction.tenant_id == ctx.tenant_id, ctx.scope(GoogleLocation.location_id))
    waiting = ctx.db.scalars(base.where(AgentAction.status == "pending_approval").order_by(AgentAction.created_at.desc()).limit(50)).all()
    running = ctx.db.scalars(base.where(AgentAction.status.in_(("approved", "executing"))).order_by(AgentAction.created_at.desc()).limit(50)).all()
    done = ctx.db.scalars(base.where(AgentAction.status == "executed").order_by(AgentAction.executed_at.desc().nullslast()).limit(30)).all()
    since = utcnow() - timedelta(days=30)
    bad = ctx.db.scalars(base.where(AgentAction.status.in_(("failed", "blocked", "invalidated", "expired")), AgentAction.created_at >= since).order_by(AgentAction.created_at.desc()).limit(50)).all()
    out = {
        "settings": _settings_out(ctx, s),
        "waiting": [executor.action_out(ctx.db, a) for a in waiting], "running": [executor.action_out(ctx.db, a) for a in running],
        "recent": [executor.action_out(ctx.db, a) for a in done], "problems": [executor.action_out(ctx.db, a) for a in bad],
        "usage": _usage(ctx),
        "can_decide": ctx.role in (Role.owner, Role.admin), "is_owner": ctx.role == Role.owner,
    }
    ctx.db.commit()
    return out


@router.post("/agent/autonomy-settings/stop")
def owner_emergency_stop(request: Request, ctx: TenantContext = Depends(require_role(Role.owner))):
    """The owner's own emergency stop. Autonomy is switched off AND marked suspended, anything that was authorised by standing policy goes back to waiting for a person
    immediately, and nothing runs on its own until the owner deliberately resumes. Actions a named person approved are not touched."""
    s = executor.get_settings(ctx.db, ctx.tenant_id)
    now = utcnow()
    s.autonomy_enabled = False
    s.autonomy_suspended_at, s.autonomy_suspended_reason = now, "Stopped by the owner with the emergency stop."
    n = executor.withdraw_autonomous(ctx.db, ctx.tenant_id, reason="The owner pressed the emergency stop.", user_id=ctx.user.id, now=now)
    audit(ctx.db, action="autonomy.owner_stop", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="agent_settings", entity_id=s.id, meta={"withdrawn": n}, ip=client_ip(request))
    out = {**_settings_out(ctx, s), "withdrawn": n}
    ctx.db.commit()
    return out
