"""WhatsApp automation for a business owner: connect their own number, manage the people they may message and the consent behind each, see which automations will be available.

Everything here answers `whatsapp_disabled` (404) while WHATSAPP_ENABLED is false. Reads are open to any member of the business; every change needs the owner or an admin of the business.
No route returns an access token, the signup state's hash or any Meta secret. Phase 1 sends nothing."""
import re
import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import TenantContext, get_tenant_context, require_role
from app.core.rate_limit import client_ip, hit
from app.models import Role
from app.models.whatsapp import WhatsAppCampaign, WhatsAppTemplate
from datetime import datetime as _dt
from app.services.whatsapp import WaError, addons, agent, ai_knowledge, automations, campaigns, connection, consent, conversations, occasions, optin, pricing, rules, setup as wa_setup, templates as wa_templates, usage

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
    occasion: bool = False  # agreed to birthday and festival greetings (a consent of its own)
    birth_day: int | None = Field(default=None, ge=1, le=31)
    birth_month: int | None = Field(default=None, ge=1, le=12)
    attested: bool = False
    evidence: str | None = Field(default=None, max_length=400)
    location_id: uuid.UUID | None = None


class ContactPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    tags: list[str] | None = Field(default=None, max_length=10)
    location_id: uuid.UUID | None = None
    birth_day: int | None = Field(default=None, ge=1, le=31)  # send both, or both as null to clear; setting them needs the "they agreed" confirmation
    birth_month: int | None = Field(default=None, ge=1, le=12)
    attested: bool = False
    evidence: str | None = Field(default=None, max_length=400)


class ConsentIn(BaseModel):
    purpose: Literal["marketing", "utility", "occasion"]
    attested: bool = False
    evidence: str | None = Field(default=None, max_length=400)


class WithdrawIn(BaseModel):
    purpose: Literal["marketing", "utility", "occasion"]


class ImportIn(BaseModel):
    csv: str = Field(min_length=3, max_length=400_000)
    purposes: list[Literal["marketing", "utility", "occasion"]] = Field(min_length=1, max_length=3)
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
def contacts(search: str | None = None, consent_filter: Literal["marketing", "utility", "opted_out", "none"] | None = None, location_id: uuid.UUID | None = None, limit: int = 50, offset: int = 0,
             ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    total, items = consent.list_contacts(ctx.db, ctx.tenant_id, search=search, consent=consent_filter, limit=max(1, min(limit, 200)), offset=max(0, offset), location_id=location_id)
    return {"total": total, "items": items, "counts": consent.counts(ctx.db, ctx.tenant_id), "wording": {p: rules.wording_for(p, ctx.tenant.name) for p in ("marketing", "utility", "occasion")}}


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
        c, created = consent.create_contact(ctx.db, ctx.tenant, phone=body.phone, name=body.name, tags=body.tags, source="owner_entry", user_id=ctx.user.id, location_id=body.location_id)
        for purpose, wanted in (("marketing", body.marketing), ("utility", body.utility), ("occasion", body.occasion)):
            if wanted:
                consent.grant(ctx.db, ctx.tenant, c, purpose, "owner_entry", user_id=ctx.user.id, attested=body.attested, evidence=body.evidence, ip=client_ip(request))
        if body.birth_day is not None or body.birth_month is not None:
            consent.set_birthday(ctx.db, c, body.birth_day, body.birth_month, attested=body.attested, evidence=body.evidence, user_id=ctx.user.id, ip=client_ip(request))
        return consent.serialize(c, consent.consent_map(ctx.db, [c.id])[c.id])
    return _run(ctx, go)


@router.post("/contacts/import")
def contacts_import(body: ImportIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    _limit(f"wa-import:{ctx.tenant_id}", 10, 3600)
    return _run(ctx, lambda: consent.import_csv(ctx.db, ctx.tenant, ctx.user.id, body.csv, attested=body.attested, evidence=body.evidence, purposes=list(body.purposes), ip=client_ip(request)))


@router.patch("/contacts/{contact_id}")
def contact_patch(contact_id: uuid.UUID, body: ContactPatch, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()

    def go():
        c = consent.get_contact(ctx.db, ctx.tenant_id, contact_id)
        if "birth_day" in body.model_fields_set or "birth_month" in body.model_fields_set:
            consent.set_birthday(ctx.db, c, body.birth_day, body.birth_month, attested=body.attested, evidence=body.evidence, user_id=ctx.user.id, ip=client_ip(request))
        consent.update_contact(ctx.db, c, name=body.name, tags=body.tags, set_name="name" in body.model_fields_set, set_tags="tags" in body.model_fields_set, location_id=body.location_id,
                               set_location="location_id" in body.model_fields_set)
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


# ---- first-run set-up: the guided path from nothing to the first helper
class PrepareIn(BaseModel):
    include_offer: bool = False
    include_optin: bool = False
    include_occasion: bool = True


class TestMessageIn(BaseModel):
    phone: str = Field(min_length=5, max_length=24)
    own_number: bool = False


@router.get("/setup")
def setup_status(ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    return wa_setup.status(ctx.db, ctx.tenant)


@router.post("/setup/prepare-messages")
def setup_prepare(body: PrepareIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """One click: submit the standard messages the helpers use to WhatsApp for approval (safe to repeat)."""
    _on()
    _limit(f"wa-template-install:{ctx.tenant_id}", 30, 3600)
    return _run(ctx, lambda: wa_setup.prepare_messages(ctx.db, ctx.tenant_id, ctx.user.id, client_ip(request), body.include_offer, body.include_optin, body.include_occasion))


@router.post("/setup/test-message")
def setup_test(body: TestMessageIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """A test message to the owner's OWN number, through the normal sender and gate."""
    _on()
    return _run(ctx, lambda: wa_setup.send_test(ctx.db, ctx.tenant, ctx.user, phone=body.phone, own_number=body.own_number, ip=client_ip(request)), commit_on_error=True)  # a failed try is kept: the checklist says so


# ---- opt-in without a phone number: the QR page's WhatsApp button and opt-in keywords
class OptinIn(BaseModel):
    qr_enabled: bool | None = None
    purpose: Literal["utility", "marketing", "both"] | None = None
    confirm_reply: bool | None = None


class KeywordIn(BaseModel):
    keyword: str = Field(min_length=3, max_length=20)
    purpose: Literal["utility", "marketing", "both"] = "utility"
    confirm_reply: bool = True


class KeywordPatch(BaseModel):
    enabled: bool | None = None
    purpose: Literal["utility", "marketing", "both"] | None = None
    confirm_reply: bool | None = None


@router.get("/optin")
def optin_get(ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    return optin.overview(ctx.db, ctx.tenant)


@router.put("/optin")
def optin_put(body: OptinIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    _limit(f"wa-optin:{ctx.tenant_id}", 60, 3600)

    def go():
        optin.set_settings(ctx.db, ctx.tenant, ctx.user, qr_enabled=body.qr_enabled, purpose=body.purpose, confirm_reply=body.confirm_reply, ip=client_ip(request))
        return optin.overview(ctx.db, ctx.tenant)
    return _run(ctx, go)


@router.post("/optin/keywords", status_code=201)
def optin_keyword_add(body: KeywordIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    _limit(f"wa-optin:{ctx.tenant_id}", 60, 3600)
    return _run(ctx, lambda: optin.serialize_keyword(optin.add_keyword(ctx.db, ctx.tenant, ctx.user, keyword=body.keyword, purpose=body.purpose, confirm_reply=body.confirm_reply, ip=client_ip(request)), ctx.tenant))


@router.patch("/optin/keywords/{keyword_id}")
def optin_keyword_patch(keyword_id: uuid.UUID, body: KeywordPatch, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    return _run(ctx, lambda: optin.serialize_keyword(optin.update_keyword(ctx.db, ctx.tenant, ctx.user, optin.get_keyword(ctx.db, ctx.tenant_id, keyword_id), enabled=body.enabled, purpose=body.purpose,
                                                                         confirm_reply=body.confirm_reply, ip=client_ip(request)), ctx.tenant))


@router.delete("/optin/keywords/{keyword_id}", status_code=204)
def optin_keyword_delete(keyword_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    _run(ctx, lambda: optin.delete_keyword(ctx.db, ctx.tenant, ctx.user, optin.get_keyword(ctx.db, ctx.tenant_id, keyword_id), client_ip(request)))
    return Response(status_code=204)


# ---- templates (the fixed, neutral messages FlowQR submits to WhatsApp for the business)
class InstallIn(BaseModel):
    key: Literal["review_followup", "enquiry_followup", "enquiry_ack", "offer", "optin_confirm", "optin_confirm_offers", "occasion_birthday", "occasion_festival"]


@router.get("/templates")
def templates(ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    rows = list(ctx.db.scalars(select(WhatsAppTemplate).where(WhatsAppTemplate.tenant_id == ctx.tenant_id).order_by(WhatsAppTemplate.template_name)))
    have = {wa_templates.key_of(r.template_name) for r in rows}
    return {"items": [wa_templates.serialize(t) for t in rows],
            "available": [{"key": k, "category": v["category"], "body": v["body"], "installed": k in have} for k, v in wa_templates.STANDARD.items()]}


@router.post("/templates/sync")
def templates_sync(request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    _limit(f"wa-template-sync:{ctx.tenant_id}", 30, 3600)
    return _run(ctx, lambda: wa_templates.sync(ctx.db, ctx.tenant_id, ctx.user.id, client_ip(request)))


@router.post("/templates/install")
def templates_install(body: InstallIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    _limit(f"wa-template-install:{ctx.tenant_id}", 30, 3600)
    return _run(ctx, lambda: wa_templates.serialize(wa_templates.install(ctx.db, ctx.tenant_id, body.key, ctx.user.id, client_ip(request))))


# ---- automations
class AutomationIn(BaseModel):
    status: Literal["on", "paused", "off"]
    config: dict | None = None


# ---- conversations and the inbox
class ConvSettingsIn(BaseModel):
    enabled: bool | None = None
    retention_days: int | None = None
    takeover_minutes: int | None = None
    debounce_seconds: int | None = None
    notify_email: bool | None = None


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    confirm_marketing: bool = False
    client_id: str | None = Field(default=None, max_length=64)  # one per press of Send, so a double click never sends twice


class ConvTemplateIn(BaseModel):
    key: str = Field(max_length=40)
    client_id: str | None = Field(default=None, max_length=64)


def _inbox(ctx: TenantContext) -> None:
    """The inbox is business-wide, so it is for people who see every location, and only while it is switched on."""
    if ctx.location_ids is not None:
        raise HTTPException(status_code=403, detail={"code": "not_for_your_role", "message": "The inbox is for people who can see every location."})
    if not conversations.enabled_for(ctx.db, ctx.tenant_id):
        raise HTTPException(status_code=404, detail={"code": "conversations_disabled", "message": "The inbox is not switched on."})


@router.get("/conversations/settings")
def conversation_settings(ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    return {"settings": conversations.serialize_settings(conversations.get_settings(ctx.db, ctx.tenant_id)), "platform_on": conversations.platform_on(), "addon_ok": bool(addons.active_addon(ctx.db, ctx.tenant_id)) or not settings.whatsapp_require_addon,
            "active": conversations.enabled_for(ctx.db, ctx.tenant_id)}


@router.put("/conversations/settings")
def conversation_settings_put(body: ConvSettingsIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    _limit(f"wa-conv-settings:{ctx.tenant_id}", 60, 3600)

    def go():
        conversations.set_settings(ctx.db, ctx.tenant, ctx.user, ip=client_ip(request), **body.model_dump())
        return {"settings": conversations.serialize_settings(conversations.get_settings(ctx.db, ctx.tenant_id)), "platform_on": conversations.platform_on(), "active": conversations.enabled_for(ctx.db, ctx.tenant_id)}
    return _run(ctx, go)


@router.get("/conversations")
def conversation_list(q: str | None = Query(default=None, max_length=80), filter: Literal["all", "needs_you", "unread", "closed"] = "all", limit: int = 50, offset: int = 0, ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    _inbox(ctx)
    return conversations.list_conversations(ctx.db, ctx.tenant_id, q=q, filter=filter, limit=limit, offset=offset)


@router.get("/conversations/{conversation_id}")
def conversation_get(conversation_id: uuid.UUID, before: _dt | None = None, ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    _inbox(ctx)
    return _run(ctx, lambda: conversations.thread(ctx.db, ctx.tenant, conversations.get(ctx.db, ctx.tenant_id, conversation_id), before=before))


@router.post("/conversations/{conversation_id}/read")
def conversation_read(conversation_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    _inbox(ctx)

    def go():
        c = conversations.get(ctx.db, ctx.tenant_id, conversation_id)
        conversations.mark_read(c)
        return {"unread": c.unread_count}
    return _run(ctx, go)


@router.post("/conversations/{conversation_id}/reply")
def conversation_reply(conversation_id: uuid.UUID, body: ReplyIn, request: Request, ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    _inbox(ctx)
    _limit(f"wa-reply:{ctx.tenant_id}:{ctx.user.id}", 60, 60)
    return _run(ctx, lambda: conversations.staff_reply(ctx.db, ctx.tenant, ctx.user, conversations.get(ctx.db, ctx.tenant_id, conversation_id), body.text, confirm_marketing=body.confirm_marketing,
                                                       client_id=body.client_id, ip=client_ip(request)), commit_on_error=True)


@router.post("/conversations/{conversation_id}/send-template")
def conversation_send_template(conversation_id: uuid.UUID, body: ConvTemplateIn, ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    _inbox(ctx)
    _limit(f"wa-reply:{ctx.tenant_id}:{ctx.user.id}", 60, 60)
    return _run(ctx, lambda: conversations.send_fallback_template(ctx.db, ctx.tenant, ctx.user, conversations.get(ctx.db, ctx.tenant_id, conversation_id), body.key, client_id=body.client_id), commit_on_error=True)


@router.post("/conversations/{conversation_id}/take-over")
def conversation_take_over(conversation_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    _inbox(ctx)
    return _run(ctx, lambda: conversations.summary(ctx.db, conversations.take_over(ctx.db, ctx.tenant, ctx.user, conversations.get(ctx.db, ctx.tenant_id, conversation_id)), None))


@router.post("/conversations/{conversation_id}/hand-back")
def conversation_hand_back(conversation_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    _inbox(ctx)
    return _run(ctx, lambda: conversations.summary(ctx.db, conversations.hand_back(ctx.db, ctx.tenant, ctx.user, conversations.get(ctx.db, ctx.tenant_id, conversation_id)), None))


@router.post("/conversations/{conversation_id}/close")
def conversation_close(conversation_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    _inbox(ctx)

    def go():
        c = conversations.get(ctx.db, ctx.tenant_id, conversation_id)
        conversations.close(c)
        return {"status": c.status}
    return _run(ctx, go)


@router.post("/conversations/{conversation_id}/reopen")
def conversation_reopen(conversation_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    _inbox(ctx)

    def go():
        c = conversations.get(ctx.db, ctx.tenant_id, conversation_id)
        conversations.reopen(c)
        return {"status": c.status}
    return _run(ctx, go)


@router.delete("/conversations/{conversation_id}", status_code=204)
def conversation_delete(conversation_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    _inbox(ctx)
    _run(ctx, lambda: conversations.delete_conversation(ctx.db, ctx.tenant, ctx.user, conversations.get(ctx.db, ctx.tenant_id, conversation_id), client_ip(request)))
    return Response(status_code=204)


# ---- the assistant (Phase 8): notes, settings, "test it", ratings, unanswered questions
class KnowledgeIn(BaseModel):
    kind: str = Field(..., max_length=14)
    title: str | None = Field(None, max_length=120)
    body: str = Field(..., max_length=ai_knowledge.MAX_BODY + 400)
    price_inr: float | str | None = None


class KnowledgePatch(BaseModel):
    title: str | None = Field(None, max_length=120)
    body: str | None = Field(None, max_length=ai_knowledge.MAX_BODY + 400)
    price_inr: float | str | None = None
    active: bool | None = None


class AiSettingsIn(BaseModel):
    enabled: bool | None = None
    acknowledge_privacy: bool = False
    tone: str | None = Field(None, max_length=200)


class TestChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=600)
    history: list[dict] = Field(default_factory=list, max_length=12)


class FeedbackIn(BaseModel):
    value: str | None = None


class PauseIn(BaseModel):
    paused: bool


class ResolveIn(BaseModel):
    ids: list[uuid.UUID] = Field(..., max_length=50)


def _ai_ctx(ctx: TenantContext) -> None:
    _on()
    if ctx.location_ids is not None:
        raise HTTPException(status_code=403, detail={"code": "not_for_your_role", "message": "The assistant settings are for people who can see every location."})


@router.get("/ai/status")
def ai_status(ctx: TenantContext = Depends(get_tenant_context)):
    _ai_ctx(ctx)
    return agent.ai_status(ctx.db, ctx.tenant)


@router.put("/ai/settings")
def ai_settings_put(body: AiSettingsIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _ai_ctx(ctx)
    _limit(f"wa-ai-settings:{ctx.tenant_id}", 60, 3600)

    def go():
        agent.set_ai_settings(ctx.db, ctx.tenant, ctx.user, enabled=body.enabled, acknowledge_privacy=body.acknowledge_privacy, tone=body.tone, set_tone="tone" in body.model_fields_set, ip=client_ip(request))
        return agent.ai_status(ctx.db, ctx.tenant)
    return _run(ctx, go)


@router.get("/ai/knowledge")
def ai_knowledge_list(ctx: TenantContext = Depends(get_tenant_context)):
    _ai_ctx(ctx)
    items = ai_knowledge.list_items(ctx.db, ctx.tenant_id)
    return {"items": [ai_knowledge.serialize_item(i) for i in items], "readiness": ai_knowledge.readiness(items), "suggestions": ai_knowledge.suggestions(ctx.tenant), "max_items": ai_knowledge.MAX_ITEMS}


@router.post("/ai/knowledge", status_code=201)
def ai_knowledge_add(body: KnowledgeIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _ai_ctx(ctx)
    _limit(f"wa-ai-knowledge:{ctx.tenant_id}", 200, 3600)
    return _run(ctx, lambda: ai_knowledge.serialize_item(ai_knowledge.create_item(ctx.db, ctx.tenant, ctx.user, kind=body.kind, title=body.title, body=body.body, price_inr=body.price_inr, ip=client_ip(request))))


@router.post("/ai/knowledge/import")
def ai_knowledge_import(request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Pre-fill from the business's own details already in FlowQR. Offers are never copied. Nothing is fetched from a website."""
    _ai_ctx(ctx)
    _limit(f"wa-ai-import:{ctx.tenant_id}", 20, 3600)
    return _run(ctx, lambda: ai_knowledge.import_existing(ctx.db, ctx.tenant, ctx.user, ip=client_ip(request)))


@router.patch("/ai/knowledge/{item_id}")
def ai_knowledge_edit(item_id: uuid.UUID, body: KnowledgePatch, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _ai_ctx(ctx)
    return _run(ctx, lambda: ai_knowledge.serialize_item(ai_knowledge.update_item(ctx.db, ctx.tenant, ctx.user, ai_knowledge.get_item(ctx.db, ctx.tenant_id, item_id), title=body.title, body=body.body, price_inr=body.price_inr,
                                                                                    active=body.active, set_price="price_inr" in body.model_fields_set, ip=client_ip(request))))


@router.delete("/ai/knowledge/{item_id}", status_code=204)
def ai_knowledge_delete(item_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _ai_ctx(ctx)
    _run(ctx, lambda: ai_knowledge.delete_item(ctx.db, ctx.tenant, ctx.user, ai_knowledge.get_item(ctx.db, ctx.tenant_id, item_id), client_ip(request)))
    return Response(status_code=204)


@router.post("/ai/test-chat")
def ai_test_chat(body: TestChatIn, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Try the assistant as a customer would. Never sent to WhatsApp, never counted against the quota."""
    _ai_ctx(ctx)
    _limit(f"wa-ai-test:{ctx.tenant_id}", 60, 3600)
    return _run(ctx, lambda: agent.test_chat(ctx.db, ctx.tenant, body.message, body.history), commit_on_error=True)


@router.get("/ai/unanswered")
def ai_unanswered(ctx: TenantContext = Depends(get_tenant_context)):
    _ai_ctx(ctx)
    return {"items": agent.list_unanswered(ctx.db, ctx.tenant_id)}


@router.post("/ai/unanswered/resolve")
def ai_unanswered_resolve(body: ResolveIn, ctx: TenantContext = Depends(require_role(Role.admin))):
    _ai_ctx(ctx)
    return _run(ctx, lambda: {"resolved": agent.resolve_unanswered(ctx.db, ctx.tenant_id, body.ids)})


@router.get("/ai/usage")
def ai_usage_summary(ctx: TenantContext = Depends(get_tenant_context)):
    _ai_ctx(ctx)
    return {**agent.usage_summary(ctx.db, ctx.tenant_id), "quota": ai_knowledge.quota_status(ctx.db, ctx.tenant_id)}


@router.post("/conversations/{conversation_id}/ai-pause")
def conversation_ai_pause(conversation_id: uuid.UUID, body: PauseIn, request: Request, ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    _inbox(ctx)
    return _run(ctx, lambda: conversations.summary(ctx.db, agent.pause_conversation(ctx.db, ctx.tenant, ctx.user, conversations.get(ctx.db, ctx.tenant_id, conversation_id), body.paused, client_ip(request)), None))


@router.post("/conversations/{conversation_id}/messages/{message_id}/feedback")
def conversation_feedback(conversation_id: uuid.UUID, message_id: uuid.UUID, body: FeedbackIn, ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    _inbox(ctx)
    return _run(ctx, lambda: agent.set_feedback(ctx.db, ctx.tenant, conversations.get(ctx.db, ctx.tenant_id, conversation_id), message_id, body.value))


# ---- birthday and festival greetings
class FestivalChoiceIn(BaseModel):
    enabled: bool


@router.get("/occasions")
def occasions_overview(ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    return occasions.overview(ctx.db, ctx.tenant)


@router.put("/occasions/festivals/{festival_id}")
def occasions_festival(festival_id: uuid.UUID, body: FestivalChoiceIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    _limit(f"wa-festival:{ctx.tenant_id}", 120, 3600)
    return _run(ctx, lambda: occasions.set_festival(ctx.db, ctx.tenant, ctx.user, festival_id, body.enabled, client_ip(request)))


@router.get("/automations")
def automations_list(ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    c = connection.connected_connection(ctx.db, ctx.tenant_id)
    addon = _addon_info(ctx.db, ctx.tenant_id)
    counts = consent.counts(ctx.db, ctx.tenant_id)
    items = []
    for a in rules.CATALOGUE:
        ready = {"connection": c is not None and c.status == "connected", "addon": bool(addon) or not settings.whatsapp_require_addon, "customers": counts[a["purpose"]] > 0}
        item = {**a, "available": bool(a.get("live")), "coming_soon": not a.get("live"), "ready": ready}
        if a["key"] in automations.DEFAULTS:
            item["state"] = automations.serialize(ctx.db, ctx.tenant_id, a["key"])
        if a["key"] == "offers":
            item["campaigns_allowed"] = campaigns.can_use_campaigns(ctx.db, ctx.tenant_id)
        items.append(item)
    return {"items": items, "limit": addon["automation_limit"] if addon else None, "active": automations.active_count(ctx.db, ctx.tenant_id), "sending": automations.sending_allowed()}


@router.put("/automations/{key}")
def automation_set(key: Literal["review_followup", "enquiry_followup", "birthday", "festival"], body: AutomationIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    _limit(f"wa-automation:{ctx.tenant_id}", 60, 3600)
    return _run(ctx, lambda: automations.set_status(ctx.db, ctx.tenant, ctx.user, key, body.status, body.config, client_ip(request)))


@router.get("/automations/{key}/runs")
def automation_runs(key: Literal["review_followup", "enquiry_followup", "birthday", "festival"], status: Literal["scheduled", "sent", "skipped", "failed", "cancelled"] | None = None, ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    return automations.list_runs(ctx.db, ctx.tenant_id, key, 50, status)


@router.post("/contacts/{contact_id}/visit")
def contact_visit(contact_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """The owner marks this customer's visit as done: schedules one neutral request for honest feedback (if the helper is on and the customer agreed to visit updates)."""
    _on()
    _limit(f"wa-visit:{ctx.tenant_id}", 300, 3600)
    def go():
        c = consent.get_contact(ctx.db, ctx.tenant_id, contact_id)
        consent.mark_visit(ctx.db, c)  # recorded whatever happens next: win-back audiences use it
        try:
            out = automations.on_visit_completed(ctx.db, ctx.tenant, c, ctx.user.id)
        except WaError as exc:
            if exc.code != "automation_off":
                raise
            out = {"scheduled": False, "reason": "automation_off"}  # the visit is saved; there is just no review request to send
        return {"visit_recorded": True, **out}
    return _run(ctx, go)


# ---- campaigns (offers)
class CampaignIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    template_id: uuid.UUID
    audience: dict = Field(default_factory=lambda: {"kind": "all"})
    variables: dict = Field(default_factory=dict)
    scheduled_at: _dt | None = None


class CampaignPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    audience: dict | None = None
    variables: dict | None = None
    scheduled_at: _dt | None = None


class ApproveIn(BaseModel):
    confirm_recipients: int = Field(ge=0)
    accept_estimate: bool = False


@router.get("/campaigns")
def campaigns_list(ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    rows = ctx.db.scalars(select(WhatsAppCampaign).where(WhatsAppCampaign.tenant_id == ctx.tenant_id).order_by(WhatsAppCampaign.created_at.desc()).limit(100))
    return {"items": [campaigns.serialize(c) for c in rows], "allowed": campaigns.can_use_campaigns(ctx.db, ctx.tenant_id), "sending": automations.sending_allowed()}


@router.post("/campaigns", status_code=201)
def campaign_create(body: CampaignIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    _limit(f"wa-campaign-create:{ctx.tenant_id}", 60, 3600)
    return _run(ctx, lambda: campaigns.serialize(campaigns.create(ctx.db, ctx.tenant, ctx.user, name=body.name, template_id=body.template_id, audience=body.audience, variables=body.variables, scheduled_at=body.scheduled_at, ip=client_ip(request))))


@router.get("/campaigns/compare")
def campaigns_compare(ctx: TenantContext = Depends(get_tenant_context)):
    """Recent campaigns side by side: what WhatsApp reported for each (never sales)."""
    _on()
    return {"items": campaigns.compare(ctx.db, ctx.tenant_id)}


@router.get("/campaigns/{campaign_id}")
def campaign_get(campaign_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    return _run(ctx, lambda: campaigns.preview(ctx.db, ctx.tenant, campaigns.get(ctx.db, ctx.tenant_id, campaign_id)))


@router.patch("/campaigns/{campaign_id}")
def campaign_patch(campaign_id: uuid.UUID, body: CampaignPatch, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    return _run(ctx, lambda: campaigns.preview(ctx.db, ctx.tenant, campaigns.update(ctx.db, ctx.tenant, campaigns.get(ctx.db, ctx.tenant_id, campaign_id), name=body.name, audience=body.audience,
                                                                                    variables=body.variables, scheduled_at=body.scheduled_at, set_schedule="scheduled_at" in body.model_fields_set)))


@router.post("/campaigns/{campaign_id}/approve")
def campaign_approve(campaign_id: uuid.UUID, body: ApproveIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """The explicit final approval. It must repeat the recipient count the owner was shown and confirm the estimated WhatsApp charge."""
    _on()
    _limit(f"wa-campaign-approve:{ctx.tenant_id}", 60, 3600)
    return _run(ctx, lambda: campaigns.preview(ctx.db, ctx.tenant, campaigns.approve(ctx.db, ctx.tenant, ctx.user, campaigns.get(ctx.db, ctx.tenant_id, campaign_id), confirm_recipients=body.confirm_recipients,
                                                                                     accept_estimate=body.accept_estimate, ip=client_ip(request))))


class RescheduleIn(BaseModel):
    scheduled_at: _dt


@router.post("/campaigns/{campaign_id}/reschedule")
def campaign_reschedule(campaign_id: uuid.UUID, body: RescheduleIn, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Move the start time of a campaign that has not started."""
    _on()
    return _run(ctx, lambda: campaigns.preview(ctx.db, ctx.tenant, campaigns.reschedule(ctx.db, ctx.tenant, ctx.user, campaigns.get(ctx.db, ctx.tenant_id, campaign_id), body.scheduled_at, client_ip(request))))


@router.post("/campaigns/{campaign_id}/duplicate", status_code=201)
def campaign_duplicate(campaign_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """A new draft with the same message and audience."""
    _on()
    _limit(f"wa-campaign-create:{ctx.tenant_id}", 60, 3600)
    return _run(ctx, lambda: campaigns.serialize(campaigns.duplicate(ctx.db, ctx.tenant, ctx.user, campaigns.get(ctx.db, ctx.tenant_id, campaign_id), client_ip(request))))


@router.post("/campaigns/{campaign_id}/{action}")
def campaign_action(campaign_id: uuid.UUID, action: Literal["pause", "resume", "cancel"], request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    fn = {"pause": campaigns.pause, "resume": campaigns.resume, "cancel": campaigns.cancel}[action]
    return _run(ctx, lambda: campaigns.serialize(fn(ctx.db, ctx.tenant, ctx.user, campaigns.get(ctx.db, ctx.tenant_id, campaign_id), client_ip(request))))


@router.get("/campaigns/{campaign_id}/results")
def campaign_results(campaign_id: uuid.UUID, ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    return _run(ctx, lambda: campaigns.results(ctx.db, ctx.tenant_id, campaigns.get(ctx.db, ctx.tenant_id, campaign_id)))


@router.get("/campaigns/{campaign_id}/results.csv")
def campaign_results_csv(campaign_id: uuid.UUID, request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    """Who the campaign went to and what happened to each message, for the owner's own records."""
    _on()
    from app.services.audit import audit
    c = _run(ctx, lambda: campaigns.get(ctx.db, ctx.tenant_id, campaign_id))
    audit(ctx.db, action="whatsapp.campaign_export", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="whatsapp_campaign", entity_id=c.id, ip=client_ip(request))
    ctx.db.commit()
    return Response(campaigns.recipients_csv(ctx.db, ctx.tenant_id, c), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="campaign-results.csv"', "Cache-Control": "no-store"})


# ---- usage and activity
@router.get("/usage")
def usage_summary(month: str | None = None, ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    out = _run(ctx, lambda: usage.summary(ctx.db, ctx.tenant_id, month))
    out["rates"] = {c: pricing.estimate(ctx.db, c, 1) for c in ("marketing", "utility")}
    out["price_warning"] = pricing.WARNING if pricing.unverified_in_use(ctx.db) else None  # shown above every cost figure while the price in use is unverified
    out["limits"] = {"per_minute": settings.whatsapp_send_per_minute, "per_day": settings.whatsapp_daily_cap}
    return out


@router.get("/messages/export")
def messages_export(request: Request, ctx: TenantContext = Depends(require_role(Role.admin))):
    _on()
    from app.services.audit import audit
    audit(ctx.db, action="whatsapp.messages_export", tenant_id=ctx.tenant_id, user_id=ctx.user.id, entity_type="whatsapp_message", ip=client_ip(request))
    ctx.db.commit()
    return Response(usage.export_csv(ctx.db, ctx.tenant_id), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="whatsapp-messages.csv"', "Cache-Control": "no-store"})


@router.get("/messages")
def message_activity(status: Literal["queued", "sent", "delivered", "read", "failed"] | None = None, campaign_id: uuid.UUID | None = None, limit: int = 50, offset: int = 0, ctx: TenantContext = Depends(get_tenant_context)):
    _on()
    total, items = usage.activity(ctx.db, ctx.tenant_id, limit=max(1, min(limit, 200)), offset=max(0, offset), status=status, campaign_id=campaign_id)
    return {"total": total, "items": items}
