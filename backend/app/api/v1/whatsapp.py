"""WhatsApp automation for a business owner: connect their own number, manage the people they may message and the consent behind each, see which automations will be available.

Everything here answers `whatsapp_disabled` (404) while WHATSAPP_ENABLED is false. Reads are open to any member of the business; every change needs the owner or an admin of the business.
No route returns an access token, the signup state's hash or any Meta secret. Phase 1 sends nothing."""
import re
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import TenantContext, get_tenant_context, require_role
from app.core.rate_limit import client_ip, hit
from app.models import Role
from app.models.whatsapp import WhatsAppTemplate
from app.services.whatsapp import WaError, addons, connection, consent, rules

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


def _on() -> None:
    try:
        connection.require_enabled()
    except WaError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.detail())


def _run(ctx: TenantContext, fn, *, commit_on_error: bool = False):
    try:
        out = fn()
        ctx.db.commit()
        return out
    except WaError as exc:
        if commit_on_error:
            ctx.db.commit()
        else:
            ctx.db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.detail())


def _limit(key: str, n: int, seconds: int) -> None:
    if not hit(key, n, seconds):
        raise HTTPException(status_code=429, detail={"code": "rate_limited", "message": "Too many attempts. Please try again later."})


class ContactIn(BaseModel):
    phone: str = Field(min_length=5, max_length=24)
    name: str | None = Field(default=None, max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=10)
    marketing: bool = False
    utility: bool = False
    attested: bool = False
    evidence: str | None = Field(default=None, max_length=400)


class ContactPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    tags: list[str] | None = Field(default=None, max_length=10)


class ConsentIn(BaseModel):
    purpose: Literal["marketing", "utility"]
    attested: bool = False
    evidence: str | None = Field(default=None, max_length=400)


class WithdrawIn(BaseModel):
    purpose: Literal["marketing", "utility"]


class ImportIn(BaseModel):
    csv: str = Field(min_length=3, max_length=400_000)
    purposes: list[Literal["marketing", "utility"]] = Field(min_length=1, max_length=2)
    attested: bool = False
    evidence: str | None = Field(default=None, max_length=400)


class CompleteIn(BaseModel):
    state: str = Field(min_length=20, max_length=200)
    code: str = Field(min_length=5, max_length=2000)
    waba_id: str = Field(max_length=40)
    phone_number_id: str = Field(max_length=40)

    @field_validator("waba_id", "phone_number_id")
    @classmethod
    def _digits(cls, v: str) -> str:
        if not re.fullmatch(r"\d{5,40}", v or ""):
            raise ValueError("invalid id")
        return v


def _addon_info(db: Session, tenant_id: uuid.UUID) -> dict | None:
    return addons.tier(addons.active_addon(db, tenant_id))


@router.get("/status")
def status(ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    c = connection.live_connection(ctx.db, ctx.tenant_id)
    addon = _addon_info(ctx.db, ctx.tenant_id)
    return {
        "enabled": True, "signup_available": connection.signup_configured(), "addon_required": settings.whatsapp_require_addon, "addon": addon,
        "tiers": [{"key": k, **v} for k, v in rules.ADDON_TIERS.items()],
        "connection": connection.serialize(c), "counts": consent.counts(ctx.db, ctx.tenant_id),
        "messaging": {"enabled": bool(settings.whatsapp_sending_enabled and not settings.whatsapp_emergency_stop), "emergency_stop": settings.whatsapp_emergency_stop},
        "can_connect": bool(connection.signup_configured() and (addon or not settings.whatsapp_require_addon) and (c is None or c.status == "pending")),
    }


@router.post("/connect/start")
def connect_start(request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    _limit(f"wa-connect-start:{ctx.tenant_id}", 20, 3600)
    return _run(ctx, lambda: connection.start_signup(ctx.db, ctx.tenant, ctx.user, client_ip(request)))


@router.post("/connect/complete")
def connect_complete(body: CompleteIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    _limit(f"wa-connect-complete:{ctx.tenant_id}", 20, 3600)
    c = _run(ctx, lambda: connection.complete_signup(ctx.db, ctx.tenant, ctx.user, state=body.state, code=body.code, waba_id=body.waba_id, phone_number_id=body.phone_number_id, ip=client_ip(request)),
             commit_on_error=True)  # a failed attempt still consumes its one-time state
    return connection.serialize(c)


@router.post("/connection/check")
def connection_check(request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    _limit(f"wa-check:{ctx.tenant_id}", 30, 3600)

    def go():
        c = connection.connected_connection(ctx.db, ctx.tenant_id)
        if c is None:
            raise WaError(404, "not_connected", "No WhatsApp number is connected.")
        return connection.serialize(connection.refresh(ctx.db, c, user_id=ctx.user.id, ip=client_ip(request)))
    return _run(ctx, go)


@router.post("/connection/disconnect")
def connection_disconnect(request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    return _run(ctx, lambda: connection.serialize(connection.disconnect(ctx.db, ctx.tenant, ctx.user, client_ip(request))))


# ---- people and consent
@router.get("/contacts")
def contacts(search: str | None = None, consent_filter: Literal["marketing", "utility", "opted_out", "none"] | None = None, limit: int = 50, offset: int = 0, ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    total, items = consent.list_contacts(ctx.db, ctx.tenant_id, search=search, consent=consent_filter, limit=max(1, min(limit, 200)), offset=max(0, offset))
    return {"total": total, "items": items, "counts": consent.counts(ctx.db, ctx.tenant_id), "wording": {p: rules.wording_for(p, ctx.tenant.name) for p in ("marketing", "utility")}}


@router.get("/contacts/export")
def contacts_export(request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    from app.services.audit import audit
    audit(ctx.db, action="whatsapp.contact_export", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="whatsapp_contact", ip=client_ip(request))
    ctx.db.commit()
    return Response(consent.export_csv(ctx.db, ctx.tenant_id), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="whatsapp-customers.csv"', "Cache-Control": "no-store"})


@router.post("/contacts", status_code=201)
def contact_add(body: ContactIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    _limit(f"wa-contact-add:{ctx.tenant_id}", 300, 3600)

    def go():
        c, created = consent.create_contact(ctx.db, ctx.tenant, phone=body.phone, name=body.name, tags=body.tags, source="owner_entry", user_id=ctx.user.id)
        for purpose, wanted in (("marketing", body.marketing), ("utility", body.utility)):
            if wanted:
                consent.grant(ctx.db, ctx.tenant, c, purpose, "owner_entry", user_id=ctx.user.id, attested=body.attested, evidence=body.evidence, ip=client_ip(request))
        return consent.serialize(c, consent.consent_map(ctx.db, [c.id])[c.id])
    return _run(ctx, go)


@router.post("/contacts/import")
def contacts_import(body: ImportIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    _limit(f"wa-import:{ctx.tenant_id}", 10, 3600)
    return _run(ctx, lambda: consent.import_csv(ctx.db, ctx.tenant, ctx.user.id, body.csv, attested=body.attested, evidence=body.evidence, purposes=list(body.purposes), ip=client_ip(request)))


@router.patch("/contacts/{contact_id}")
def contact_patch(contact_id: uuid.UUID, body: ContactPatch, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()

    def go():
        c = consent.get_contact(ctx.db, ctx.tenant_id, contact_id)
        consent.update_contact(ctx.db, c, name=body.name, tags=body.tags, set_name="name" in body.model_fields_set, set_tags="tags" in body.model_fields_set)
        return consent.serialize(c, consent.consent_map(ctx.db, [c.id])[c.id])
    return _run(ctx, go)


@router.post("/contacts/{contact_id}/consent")
def contact_consent(contact_id: uuid.UUID, body: ConsentIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()

    def go():
        c = consent.get_contact(ctx.db, ctx.tenant_id, contact_id)
        consent.grant(ctx.db, ctx.tenant, c, body.purpose, "owner_entry", user_id=ctx.user.id, attested=body.attested, evidence=body.evidence, ip=client_ip(request))
        return consent.serialize(c, consent.consent_map(ctx.db, [c.id])[c.id])
    return _run(ctx, go)


@router.post("/contacts/{contact_id}/opt-out")
def contact_opt_out(contact_id: uuid.UUID, body: WithdrawIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()

    def go():
        c = consent.get_contact(ctx.db, ctx.tenant_id, contact_id)
        consent.withdraw(ctx.db, ctx.tenant, c, body.purpose, source="owner", user_id=ctx.user.id, ip=client_ip(request))
        return consent.serialize(c, consent.consent_map(ctx.db, [c.id])[c.id])
    return _run(ctx, go)


@router.delete("/contacts/{contact_id}", status_code=204)
def contact_erase(contact_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()

    def go():
        consent.erase_contact(ctx.db, ctx.tenant, consent.get_contact(ctx.db, ctx.tenant_id, contact_id), ctx.user.id, client_ip(request))
    _run(ctx, go)
    return Response(status_code=204)


# ---- templates and the catalogue
@router.get("/templates")
def templates(ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    rows = ctx.db.scalars(select(WhatsAppTemplate).where(WhatsAppTemplate.tenant_id == ctx.tenant_id).order_by(WhatsAppTemplate.template_name))
    return [{"id": t.id, "name": t.template_name, "language": t.language, "category": t.category, "status": t.approval_status, "body": t.body_text, "rejection_reason": t.rejection_reason,
             "synced_at": t.last_synced_at} for t in rows]


@router.get("/automations")
def automations(ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    c = connection.connected_connection(ctx.db, ctx.tenant_id)
    addon = _addon_info(ctx.db, ctx.tenant_id)
    counts = consent.counts(ctx.db, ctx.tenant_id)
    items = []
    for a in rules.CATALOGUE:
        ready = {"connection": c is not None and c.status == "connected", "addon": bool(addon) or not settings.whatsapp_require_addon, "customers": counts["marketing" if a["purpose"] == "marketing" else "utility"] > 0}
        items.append({**a, "available": False, "coming_soon": True, "ready": ready})
    return {"items": items, "limit": addon["automation_limit"] if addon else None}
