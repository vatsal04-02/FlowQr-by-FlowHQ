"""WhatsApp opt-in without collecting a phone number.

Two ways for a customer to opt in by sending a message to the business's own connected number:
  * the QR page's button: a click-to-chat (wa.me) link whose prefilled text is the consent wording plus a short per-business code;
  * an opt-in keyword (up to 5 per business) the owner shows on a sign, a bill or a screen.
The message the customer sends IS the consent. So:
  * it counts only if it arrives on a verified connected number (the webhook checked the signature and found the business from the number, never from the message);
  * the QR message must equal the prefilled text EXACTLY (same sentence, same code), and a keyword must be the whole message. A customer who edits the sentence, or a message that merely contains the code
    or the word, creates nothing (fail closed);
  * the consent covers only the purpose the wording names (updates | offers | both), is stored with that exact wording, a version and the time, and its source is qr_click_to_chat or keyword_opt_in;
  * these are the customer's own act, so they can lift an earlier opt-out of the same purpose; an owner, a CSV or an administrator never can;
  * STOP is checked first and always wins; keywords can never be a STOP word;
  * one confirmation is sent through the NORMAL sender and gate (approved template, consent for its real category, limits, emergency stop), only when a consent was newly recorded, so a repeat sends nothing.
"""
import logging
import re
import secrets
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Tenant, User
from app.models.whatsapp import WhatsAppConnection, WhatsAppOptinKeyword, WhatsAppOptinSettings
from app.services.audit import audit
from app.services.whatsapp import WaError, addons, connection, consent, rules, sender, templates

log = logging.getLogger("flowqr.whatsapp.optin")
MAX_KEYWORDS = 5
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I: easy to read and to type
PURPOSES = {"utility": ["utility"], "marketing": ["marketing"], "both": ["utility", "marketing"]}


class TransientOptinError(Exception):
    """The confirmation could not be sent right now. Raised so the worker retries the whole event (consent is idempotent)."""


def _new_code(db: Session) -> str:
    for _ in range(20):
        c = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        if db.scalar(select(WhatsAppOptinSettings.id).where(WhatsAppOptinSettings.code == c)) is None:
            return c
    raise WaError(500, "code_failed", "Could not make a code. Please try again.")


def get_settings(db: Session, tenant_id: uuid.UUID, create: bool = False) -> WhatsAppOptinSettings | None:
    s = db.scalar(select(WhatsAppOptinSettings).where(WhatsAppOptinSettings.tenant_id == tenant_id))
    if s is None and create:
        s = WhatsAppOptinSettings(tenant_id=tenant_id, code=_new_code(db), qr_enabled=False, purpose="utility", confirm_reply=True)
        db.add(s)
        db.flush()
    return s


def prefill(s: WhatsAppOptinSettings, tenant: Tenant) -> str:
    return rules.optin_text(s.purpose, tenant.name, s.code)


def set_settings(db: Session, tenant: Tenant, user: User, *, qr_enabled: bool | None, purpose: str | None, confirm_reply: bool | None, ip: str | None = None) -> WhatsAppOptinSettings:
    s = get_settings(db, tenant.id, create=True)
    before = (s.qr_enabled, s.purpose, s.confirm_reply)
    if purpose is not None:
        if purpose not in PURPOSES:
            raise WaError(422, "invalid_purpose", "Choose updates, offers or both.")
        s.purpose = purpose
    if qr_enabled is not None:
        s.qr_enabled = qr_enabled
    if confirm_reply is not None:
        s.confirm_reply = confirm_reply
    db.flush()
    audit(db, action="whatsapp.optin_settings", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_optin_settings", entity_id=s.id,
          meta={"from": {"qr": before[0], "purpose": before[1], "confirm": before[2]}, "to": {"qr": s.qr_enabled, "purpose": s.purpose, "confirm": s.confirm_reply}}, ip=ip)
    return s


# ---- keywords
def list_keywords(db: Session, tenant_id: uuid.UUID) -> list[WhatsAppOptinKeyword]:
    return list(db.scalars(select(WhatsAppOptinKeyword).where(WhatsAppOptinKeyword.tenant_id == tenant_id).order_by(WhatsAppOptinKeyword.created_at)))


def add_keyword(db: Session, tenant: Tenant, user: User, *, keyword: str, purpose: str, confirm_reply: bool, ip: str | None = None) -> WhatsAppOptinKeyword:
    k = (keyword or "").strip().lower()
    problem = rules.keyword_problem(k)
    if problem:
        raise WaError(422, "invalid_keyword", problem)
    if purpose not in PURPOSES:
        raise WaError(422, "invalid_purpose", "Choose updates, offers or both.")
    if (db.scalar(select(func.count()).select_from(WhatsAppOptinKeyword).where(WhatsAppOptinKeyword.tenant_id == tenant.id)) or 0) >= MAX_KEYWORDS:
        raise WaError(409, "too_many_keywords", f"You can have up to {MAX_KEYWORDS} opt-in words. Remove one first.")
    if db.scalar(select(WhatsAppOptinKeyword.id).where(WhatsAppOptinKeyword.tenant_id == tenant.id, WhatsAppOptinKeyword.keyword == k)):
        raise WaError(409, "keyword_exists", "You already have that word.")
    row = WhatsAppOptinKeyword(tenant_id=tenant.id, keyword=k, purpose=purpose, confirm_reply=confirm_reply, enabled=True)
    db.add(row)
    db.flush()
    audit(db, action="whatsapp.optin_keyword_add", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_optin_keyword", entity_id=row.id, meta={"keyword": k, "purpose": purpose}, ip=ip)
    return row


def get_keyword(db: Session, tenant_id: uuid.UUID, keyword_id: uuid.UUID) -> WhatsAppOptinKeyword:
    row = db.scalar(select(WhatsAppOptinKeyword).where(WhatsAppOptinKeyword.id == keyword_id, WhatsAppOptinKeyword.tenant_id == tenant_id))
    if row is None:
        raise WaError(404, "not_found", "That word was not found.")
    return row


def update_keyword(db: Session, tenant: Tenant, user: User, row: WhatsAppOptinKeyword, *, enabled: bool | None, purpose: str | None, confirm_reply: bool | None, ip: str | None = None) -> WhatsAppOptinKeyword:
    if purpose is not None:
        if purpose not in PURPOSES:
            raise WaError(422, "invalid_purpose", "Choose updates, offers or both.")
        row.purpose = purpose
    if enabled is not None:
        row.enabled = enabled
    if confirm_reply is not None:
        row.confirm_reply = confirm_reply
    audit(db, action="whatsapp.optin_keyword_update", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_optin_keyword", entity_id=row.id, meta={"enabled": row.enabled, "purpose": row.purpose}, ip=ip)
    return row


def delete_keyword(db: Session, tenant: Tenant, user: User, row: WhatsAppOptinKeyword, ip: str | None = None) -> None:
    audit(db, action="whatsapp.optin_keyword_delete", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_optin_keyword", entity_id=row.id, meta={"keyword": row.keyword}, ip=ip)
    db.delete(row)


def serialize_keyword(row: WhatsAppOptinKeyword, tenant: Tenant) -> dict:
    return {"id": row.id, "keyword": row.keyword, "purpose": row.purpose, "enabled": row.enabled, "confirm_reply": row.confirm_reply, "wording": rules.keyword_wording(row.keyword, row.purpose, tenant.name)}


def overview(db: Session, tenant: Tenant) -> dict:
    s = get_settings(db, tenant.id)
    conn = connection.connected_connection(db, tenant.id)
    link = public_link(db, tenant)
    confirm = {}
    for key in ("optin_confirm", "optin_confirm_offers"):
        row = templates.standard_row(db, tenant.id, key)
        confirm[key] = row.approval_status if row else None
    return {"settings": None if s is None else {"code": s.code, "qr_enabled": s.qr_enabled, "purpose": s.purpose, "confirm_reply": s.confirm_reply, "prefill_text": prefill(s, tenant)},
            "keywords": [serialize_keyword(k, tenant) for k in list_keywords(db, tenant.id)], "max_keywords": MAX_KEYWORDS, "connected": bool(conn and conn.status == "connected"),
            "link_live": link is not None, "link_example": link["url"] if link else None, "confirm_templates": confirm, "purpose_words": rules.PURPOSE_WORDS}


# ---- the public QR page
def _digits(display: str | None) -> str | None:
    d = re.sub(r"\D", "", display or "")
    return d if 8 <= len(d) <= 15 else None


def public_link(db: Session, tenant: Tenant) -> dict | None:
    """What the public QR review page may show: a click-to-chat link to the business's connected number. Nothing is collected on the page. None unless WhatsApp is on, the business switched this on,
    its number is connected and (where required) the add-on is active."""
    if not settings.whatsapp_enabled:
        return None
    s = get_settings(db, tenant.id)
    if s is None or not s.qr_enabled:
        return None
    if settings.whatsapp_require_addon and addons.active_addon(db, tenant.id) is None:
        return None
    conn = connection.connected_connection(db, tenant.id)
    digits = _digits(conn.display_phone_number) if conn is not None and conn.status == "connected" else None
    if not digits:
        return None
    from urllib.parse import quote
    text = prefill(s, tenant)
    return {"url": f"https://wa.me/{digits}?text={quote(text, safe='')}", "purpose": s.purpose, "purpose_words": rules.PURPOSE_WORDS[s.purpose], "text": text}


# ---- the inbound message
def _match(db: Session, tenant: Tenant, text: str) -> tuple[str, str, str, str, bool] | None:
    """(source, purpose, wording, version, confirm) when `text` is exactly an opt-in; otherwise None."""
    n = rules.norm_text(text)
    s = get_settings(db, tenant.id)
    if s is not None and s.qr_enabled and n == rules.norm_text(prefill(s, tenant)):
        wording = prefill(s, tenant)
        return "qr_click_to_chat", s.purpose, wording, rules.OPTIN_WORDING_VERSION, s.confirm_reply
    whole = re.sub(r"[\s.!]+$", "", n)
    row = db.scalar(select(WhatsAppOptinKeyword).where(WhatsAppOptinKeyword.tenant_id == tenant.id, WhatsAppOptinKeyword.keyword == whole, WhatsAppOptinKeyword.enabled.is_(True)))
    if row is not None:
        return "keyword_opt_in", row.purpose, rules.keyword_wording(row.keyword, row.purpose, tenant.name), rules.OPTIN_WORDING_VERSION, row.confirm_reply
    return None


def handle_inbound(db: Session, tenant: Tenant, phone: str, text: str | None, wamid: str) -> dict | None:
    """A customer's message arrived on this business's verified number. If it is an opt-in, record consent and (once) confirm. Returns None when it is not an opt-in."""
    if not text or not settings.whatsapp_enabled:
        return None
    hit = _match(db, tenant, text)
    if hit is None:
        return None
    source, purpose, wording, version, confirm = hit
    try:
        contact, _ = consent.create_contact(db, tenant, phone=phone, name=None, tags=[], source=source, user_id=None)
    except WaError:
        return None  # not a usable number
    made = False
    for p in PURPOSES[purpose]:
        _, m = consent.grant(db, tenant, contact, p, source, wording_text=wording, wording_version=version)
        made = made or m
    replied = False
    if made and confirm:
        key = "optin_confirm_offers" if purpose == "marketing" else "optin_confirm"
        row = templates.standard_row(db, tenant.id, key)
        if row is not None:
            res = sender.send_template(db, tenant, contact, row, [templates.first_name(contact.customer_name), tenant.name, rules.PURPOSE_WORDS[purpose]], idem_key=f"optin:{tenant.id}:{contact.id}:{wamid or 'x'}", kind="optin_confirm")
            if res.status == "retry":
                raise TransientOptinError(res.reason)
            replied = res.status == "sent"
    return {"contact_id": contact.id, "source": source, "purpose": purpose, "new_consent": made, "confirmed": replied}
