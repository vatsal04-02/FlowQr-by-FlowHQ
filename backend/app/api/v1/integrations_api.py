"""The inbound API a business's own systems call with an API key (Phase 10). Authentication is the key, not a login: no cookie, no CSRF, so a browser can never be tricked into calling it.

Every POST needs an Idempotency-Key. Nothing here creates consent unless the request carries consent.agreed true and a written note of how the customer agreed. Off unless
WHATSAPP_INTEGRATIONS_ENABLED, and for Pro businesses only. See docs/WHATSAPP_INTEGRATIONS_API.md."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.db import get_db, set_rls_context
from app.models import Tenant
from app.models.whatsapp import WhatsAppApiKey
from app.services.whatsapp import WaError, integrations

router = APIRouter(prefix="/integrations/v1", tags=["integrations"])


@dataclass
class ApiContext:
    db: Session
    key: WhatsAppApiKey
    tenant: Tenant


def _deny(status: int, code: str, message: str, headers: dict | None = None) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message}, headers=headers)


def api_context(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> ApiContext:
    token = authorization[7:].strip() if authorization and authorization[:7].lower() == "bearer " else None
    set_rls_context(db, bypass=True)  # the tenant is not known until the key is
    key = integrations.authenticate(db, token)
    if key is None:
        set_rls_context(db)
        raise _deny(401, "invalid_key", "The API key is missing, wrong, expired or revoked.", {"WWW-Authenticate": "Bearer"})
    tenant = db.get(Tenant, key.tenant_id)
    if tenant is None or not tenant.is_active or not integrations.enabled_for(db, tenant.id):
        set_rls_context(db)
        raise _deny(403, "integrations_off", "Integrations are not available for this business.")
    if not integrations.check_rate(key):
        set_rls_context(db)
        raise _deny(429, "rate_limited", "Too many requests. Slow down.", {"Retry-After": "60"})
    set_rls_context(db, tenant_id=tenant.id)
    return ApiContext(db=db, key=key, tenant=tenant)


def scoped(scope: str):
    def dep(ctx: ApiContext = Depends(api_context)) -> ApiContext:
        if scope not in (ctx.key.scopes or []):
            raise _deny(403, "insufficient_scope", f"This key does not have the {scope} scope.")
        return ctx
    return dep


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConsentIn(_Strict):
    purposes: list[str] = Field(..., min_length=1, max_length=3)
    agreed: bool
    evidence: str = Field(..., max_length=400)


class CustomerIn(_Strict):
    phone: str = Field(..., min_length=5, max_length=32)
    name: str | None = Field(None, max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=10)
    consent: ConsentIn | None = None


class VisitIn(_Strict):
    phone: str = Field(..., min_length=5, max_length=32)
    visited_at: str | None = Field(None, max_length=40)


class EnquiryIn(_Strict):
    phone: str = Field(..., min_length=5, max_length=32)
    name: str | None = Field(None, max_length=120)
    consent: ConsentIn | None = None


class BookingIn(_Strict):
    phone: str = Field(..., min_length=5, max_length=32)
    name: str | None = Field(None, max_length=120)
    service: str = Field(..., min_length=1, max_length=120)
    date: str = Field(..., max_length=10)
    time: str = Field(..., max_length=5)
    note: str | None = Field(None, max_length=300)


def _run(ctx: ApiContext, path: str, body: BaseModel, idem: str | None, work, ok_status: int = 200):
    try:
        status, response, replay = integrations.idempotent(ctx.db, ctx.key, idem, path, body.model_dump(), lambda: (ok_status, work()))
        ctx.db.commit()
    except WaError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.detail())
    return JSONResponse(response, status_code=status, headers={"Idempotent-Replay": "true"} if replay else {})


@router.get("/me")
def me(ctx: ApiContext = Depends(api_context)):
    """Who this key is and what it may do: a safe call to check a new key."""
    ctx.db.commit()
    return {"business": ctx.tenant.name, "key": {"name": ctx.key.name, "prefix": ctx.key.prefix, "scopes": list(ctx.key.scopes or []), "rate_limit_per_min": ctx.key.rate_limit_per_min}, "api_version": integrations.API_VERSION}


@router.post("/customers")
def customers(body: CustomerIn, idempotency_key: str | None = Header(default=None), ctx: ApiContext = Depends(scoped("customers:write"))):
    return _run(ctx, "/customers", body, idempotency_key, lambda: integrations.upsert_customer(ctx.db, ctx.tenant, body.model_dump()))


@router.post("/visits")
def visits(body: VisitIn, idempotency_key: str | None = Header(default=None), ctx: ApiContext = Depends(scoped("visits:write"))):
    return _run(ctx, "/visits", body, idempotency_key, lambda: integrations.record_visit(ctx.db, ctx.tenant, body.model_dump()))


@router.post("/enquiries")
def enquiries(body: EnquiryIn, idempotency_key: str | None = Header(default=None), ctx: ApiContext = Depends(scoped("enquiries:write"))):
    return _run(ctx, "/enquiries", body, idempotency_key, lambda: integrations.add_enquiry(ctx.db, ctx.tenant, body.model_dump()))


@router.post("/bookings", status_code=201)
def bookings_create(body: BookingIn, idempotency_key: str | None = Header(default=None), ctx: ApiContext = Depends(scoped("bookings:write"))):
    return _run(ctx, "/bookings", body, idempotency_key, lambda: integrations.create_booking(ctx.db, ctx.tenant, ctx.key, idempotency_key or "", body.model_dump()), ok_status=201)
