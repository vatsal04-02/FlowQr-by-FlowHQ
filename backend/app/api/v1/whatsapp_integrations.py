"""Owner screens for integrations (Phase 10): API keys, webhook endpoints and the delivery log. Owners and admins only; off unless WHATSAPP_INTEGRATIONS_ENABLED and the Pro add-on."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.core.deps import TenantContext, require_role
from app.core.rate_limit import client_ip, hit
from app.models import Role
from app.services.whatsapp import WaError, addons, connection, integrations

router = APIRouter(prefix="/whatsapp/integrations", tags=["whatsapp-integrations"])


def _gate(ctx: TenantContext, *, need_plan: bool = True) -> None:
    try:
        connection.require_enabled()
    except WaError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail())
    if ctx.location_ids is not None:
        raise HTTPException(status_code=403, detail={"code": "not_for_your_role", "message": "Integrations are for people who can see every location."})
    if not integrations.platform_on():
        raise HTTPException(status_code=404, detail={"code": "integrations_disabled", "message": "Integrations are not switched on for everyone yet."})
    if need_plan and not addons.integrations_allowed(ctx.db, ctx.tenant_id):
        raise HTTPException(status_code=403, detail={"code": "plan_required", "message": "Integrations are part of the WhatsApp Pro add-on."})


def _run(ctx: TenantContext, fn):
    try:
        out = fn()
        ctx.db.commit()
        return out
    except WaError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.detail())


class KeyIn(BaseModel):
    name: str = Field(..., max_length=80)
    scopes: list[str] = Field(..., max_length=4)
    rate_limit_per_min: int = 60
    expires_in_days: int | None = None


class EndpointIn(BaseModel):
    url: str = Field(..., max_length=500)
    events: list[str] = Field(..., max_length=5)


class EndpointPatch(BaseModel):
    url: str | None = Field(None, max_length=500)
    events: list[str] | None = Field(None, max_length=5)
    active: bool | None = None
    rotate_secret: bool = False


@router.get("")
def overview(ctx: TenantContext = Depends(require_role(Role.admin))):
    _gate(ctx, need_plan=False)
    return integrations.overview(ctx.db, ctx.tenant)


@router.post("/keys", status_code=201)
def key_create(body: KeyIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """The key is in this answer and nowhere else: it cannot be shown again."""
    _gate(ctx)
    if not hit(f"wa-int-key:{ctx.tenant_id}", 30, 3600):
        raise HTTPException(status_code=429, detail={"code": "rate_limited", "message": "Too many attempts. Please try again later."})

    def go():
        row, key = integrations.create_key(ctx.db, ctx.tenant, ctx.user, name=body.name, scopes=body.scopes, rate_limit_per_min=body.rate_limit_per_min, expires_in_days=body.expires_in_days, ip=client_ip(request))
        return {**integrations.serialize_key(row), "key": key, "note": "Copy this key now. It is not stored and cannot be shown again."}
    return _run(ctx, go)


@router.post("/keys/{key_id}/revoke")
def key_revoke(key_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _gate(ctx, need_plan=False)
    return _run(ctx, lambda: integrations.serialize_key(integrations.revoke_key(ctx.db, ctx.tenant, ctx.user, key_id, client_ip(request))))


@router.post("/endpoints", status_code=201)
def endpoint_create(body: EndpointIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _gate(ctx)

    def go():
        row, secret = integrations.create_endpoint(ctx.db, ctx.tenant, ctx.user, url=body.url, events=body.events, ip=client_ip(request))
        return {**integrations.serialize_endpoint(row), "secret": secret, "note": "Copy the signing secret now. It cannot be shown again; you can replace it."}
    return _run(ctx, go)


@router.patch("/endpoints/{endpoint_id}")
def endpoint_update(endpoint_id: uuid.UUID, body: EndpointPatch, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _gate(ctx)

    def go():
        e, secret = integrations.update_endpoint(ctx.db, ctx.tenant, ctx.user, integrations.get_endpoint(ctx.db, ctx.tenant_id, endpoint_id), url=body.url, events=body.events, active=body.active, rotate_secret=body.rotate_secret, ip=client_ip(request))
        return {**integrations.serialize_endpoint(e), **({"secret": secret, "note": "Copy the new signing secret now. The old one no longer works."} if secret else {})}
    return _run(ctx, go)


@router.delete("/endpoints/{endpoint_id}", status_code=204)
def endpoint_delete(endpoint_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _gate(ctx, need_plan=False)
    _run(ctx, lambda: integrations.delete_endpoint(ctx.db, ctx.tenant, ctx.user, integrations.get_endpoint(ctx.db, ctx.tenant_id, endpoint_id), client_ip(request)))
    return Response(status_code=204)


@router.post("/endpoints/{endpoint_id}/test")
def endpoint_test(endpoint_id: uuid.UUID, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Send a signed "ping" through the same path and the same address checks as every real event."""
    _gate(ctx)
    if not hit(f"wa-int-test:{ctx.tenant_id}", 30, 3600):
        raise HTTPException(status_code=429, detail={"code": "rate_limited", "message": "Too many tests. Please try again later."})
    return _run(ctx, lambda: integrations.serialize_delivery(integrations.send_test(ctx.db, ctx.tenant, integrations.get_endpoint(ctx.db, ctx.tenant_id, endpoint_id))))


@router.get("/deliveries")
def deliveries(ctx: TenantContext = Depends(require_role(Role.admin))):
    _gate(ctx, need_plan=False)
    return {"items": integrations.recent_deliveries(ctx.db, ctx.tenant_id)}


@router.post("/deliveries/{delivery_id}/retry")
def delivery_retry(delivery_id: uuid.UUID, ctx: TenantContext = Depends(require_role(Role.admin))):
    _gate(ctx)
    return _run(ctx, lambda: integrations.serialize_delivery(integrations.retry_delivery(ctx.db, ctx.tenant_id, delivery_id)))
