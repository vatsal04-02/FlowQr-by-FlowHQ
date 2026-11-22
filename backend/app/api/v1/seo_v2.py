"""Local SEO engine V2 API: the optimisation dashboard, and the changes an owner asks for (holiday hours, attribute answers, services, service area).

Approving, rejecting and cancelling a proposed change use the existing /agent/actions/{id}/... endpoints: there is ONE action system. Nothing here writes to Google: a request creates a
PROPOSAL that is classified, validated, gated by the customer-write policy gate (services/agent/v2/gate.py) and decided by a person like any other change.
Owner/admin only; the proposals themselves need the profile-management plan feature. Reading the dashboard needs only access to the location."""
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.api.v1.autonomy_actions import _err, _gloc
from app.core.deps import TenantContext, get_tenant_context, require_role
from app.core.rate_limit import client_ip
from app.models import GoogleLocation, Role
from app.services import entitlements as ent
from app.services.agent import autonomy_policy as pol
from app.services.agent import executor
from app.services.agent.v2 import fields as v2f
from app.services.agent.v2 import overview, owner
from app.services.audit import audit

router = APIRouter(prefix="/seo/v2", tags=["local-seo-v2"])


@router.get("/overview")
def v2_overview(location_id: uuid.UUID | None = None, ctx: TenantContext = Depends(get_tenant_context)):
    """Everything the optimisation dashboard shows, per location. Counts and values only from the database and Google's own answers; nothing invented."""
    q = select(GoogleLocation).where(GoogleLocation.tenant_id == ctx.tenant_id, GoogleLocation.selected.is_(True))
    if location_id:
        q = q.where(GoogleLocation.location_id == location_id)
    glocs = [g for g in ctx.db.scalars(q.order_by(GoogleLocation.title)) if ctx.can_access_location(g.location_id)]
    out = overview.build(ctx.db, ctx.tenant, glocs)
    ctx.db.commit()  # the overview may create the (empty) knowledge and settings rows it reads
    return out


def _finish(ctx: TenantContext, request: Request, a, kind: str) -> dict:
    audit(ctx.db, action=f"seo.v2.{kind}", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="agent_action", entity_id=a.id,
          meta={"type": a.action_type, "level": a.policy_level, "status": a.status}, ip=client_ip(request))
    out = executor.action_out(ctx.db, a, detail=True)
    ctx.db.commit()
    return out


def _run(ctx: TenantContext, request: Request, kind: str, fn):
    ent.require_feature(ctx.db, ctx.tenant_id, "gbp_info")
    try:
        a = fn()
    except (pol.PolicyError, executor.ActionError, v2f.FieldError) as exc:
        ctx.db.rollback()
        raise _err(exc) if not isinstance(exc, v2f.FieldError) else HTTPException(status_code=422, detail=str(exc))
    return _finish(ctx, request, a, kind)


class SpecialPeriod(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: str = Field(min_length=10, max_length=10)
    end: str | None = Field(default=None, max_length=10)
    closed: bool = False
    open: str | None = Field(default=None, max_length=5)
    close: str | None = Field(default=None, max_length=5)


class SpecialHoursIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    google_location_id: uuid.UUID
    entries: list[SpecialPeriod] = Field(min_length=1, max_length=30)


@router.post("/special-hours", status_code=201)
def add_special_hours(body: SpecialHoursIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    gl = _gloc(ctx, body.google_location_id)
    return _run(ctx, request, "special_hours", lambda: owner.propose_special_hours(ctx.db, ctx.tenant, gl, user_id=ctx.user.id, entries=[e.model_dump() for e in body.entries]))


class AttributeAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=160)
    value: Any


class AttributesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    google_location_id: uuid.UUID
    answers: list[AttributeAnswer] = Field(min_length=1, max_length=40)


@router.post("/attributes", status_code=201)
def answer_attributes(body: AttributesIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    gl = _gloc(ctx, body.google_location_id)
    return _run(ctx, request, "attributes", lambda: owner.propose_attributes(ctx.db, ctx.tenant, gl, user_id=ctx.user.id, answers=[a.model_dump() for a in body.answers]))


class ServicesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    google_location_id: uuid.UUID
    names: list[str] = Field(min_length=1, max_length=30)


@router.post("/services", status_code=201)
def add_services(body: ServicesIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    gl = _gloc(ctx, body.google_location_id)
    return _run(ctx, request, "services", lambda: owner.propose_services(ctx.db, ctx.tenant, gl, user_id=ctx.user.id, names=[n[:140] for n in body.names]))


class Place(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=200)
    place_id: str = Field(min_length=3, max_length=200)


class ServiceAreaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    google_location_id: uuid.UUID
    places: list[Place] = Field(min_length=1, max_length=20)


@router.post("/service-area", status_code=201)
def set_service_area(body: ServiceAreaIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    gl = _gloc(ctx, body.google_location_id)
    return _run(ctx, request, "service_area", lambda: owner.propose_service_area(ctx.db, ctx.tenant, gl, user_id=ctx.user.id, places=[p.model_dump() for p in body.places]))
