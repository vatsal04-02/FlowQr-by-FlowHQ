"""Two-way conversations and the inbox (Phase 7).

What this is: when a customer writes to a business, the message is kept (as text, for a retention period the business chooses), the owner and staff see it in an inbox and can reply, and (Phase 8)
an assistant may answer. This module is the foundation: storing, the 24-hour window, who sent what, taking over, notifying a person, and purging.

Rules that hold here and nowhere else may bend them:
  * STOP and opt-in keyword messages never reach this module: they are recognised first (webhook.process_event) and no text of them is stored beyond the consent record.
  * Every outbound message goes through sender.send_service_reply (the single gate). This module never calls Meta.
  * A customer writing to us gives NO consent. A customer who is new gets a contact with no consent, labelled "Contact, no consent": excluded from every audience and every template send by the
    existing consent gate, and purged with the conversation retention if they never consent or book.
  * The assistant (Phase 8) is called from here, only after the wait for more messages ends, and every failure ends with a person being told, never with silence.
  * Message text is kept for `retention_days` (30 to 365, default 90) and then deleted. It is exported with the business and deleted with the customer and the business.
"""
import logging
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Membership, Role, Tenant, User
from app.models.base import utcnow
from app.models.whatsapp import (WhatsAppConsent, WhatsAppContact, WhatsAppConversation, WhatsAppConversationMessage, WhatsAppConversationSettings, WhatsAppMessage)
from app.services import mailer
from app.services.audit import audit
from app.services.whatsapp import WaError, addons, consent, rules, sender, templates

log = logging.getLogger("flowqr.whatsapp.conversations")
WINDOW = timedelta(hours=24)
NOTIFY_GAP = timedelta(hours=1)
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no 0/O/1/I
PAGE = 50
FALLBACK_TEMPLATE = "enquiry_followup"
SEND_PROBLEMS = {
    "window_closed": (409, "The 24-hour window has closed. WhatsApp only allows an approved message now."),
    "no_customer_message": (409, "This customer has not written to you, so a free reply is not allowed."),
    "marketing_warning": (409, "This looks like an offer or discount. A conversation reply cannot be marketing."),
    "marketing_content": (422, "A conversation reply cannot contain an offer or discount."),
    "conversations_disabled": (409, "The inbox is not switched on."),
    "invalid_text": (422, "Write a message first, up to the length WhatsApp allows."),
    "rate_limited": (429, "You are sending too fast. Try again in a minute."),
    "daily_cap": (429, "The daily sending limit was reached."),
    "meta_unavailable": (503, "WhatsApp is busy right now. Please try again."),
    "meta_rejected": (502, "WhatsApp did not accept the message."),
    "emergency_stop": (409, "Sending is paused for everyone for now."),
    "sending_disabled": (409, "Sending is not switched on yet."),
    "not_connected": (409, "Your WhatsApp number is not connected."),
    "token_expired": (409, "Your WhatsApp connection needs renewing."),
    "no_addon": (402, "The WhatsApp add-on is not on."),
    "whatsapp_disabled": (404, "WhatsApp is not available."),
}


# ---- settings
def get_settings(db: Session, tenant_id: uuid.UUID, *, create: bool = False) -> WhatsAppConversationSettings | None:
    row = db.scalar(select(WhatsAppConversationSettings).where(WhatsAppConversationSettings.tenant_id == tenant_id))
    if row is None and create:
        row = WhatsAppConversationSettings(tenant_id=tenant_id, enabled=False, retention_days=90, takeover_minutes=60, debounce_seconds=4, notify_email=True)
        db.add(row)
        db.flush()
    return row


def platform_on() -> bool:
    return bool(settings.whatsapp_enabled and settings.whatsapp_conversations_enabled)


def enabled_for(db: Session, tenant_id: uuid.UUID) -> bool:
    """The platform switch, the business's own switch, and (where the add-on is required) an active add-on. Inbox: every tier."""
    if not platform_on():
        return False
    s = get_settings(db, tenant_id)
    if s is None or not s.enabled:
        return False
    return not settings.whatsapp_require_addon or addons.active_addon(db, tenant_id) is not None


def serialize_settings(s: WhatsAppConversationSettings | None) -> dict:
    s = s or WhatsAppConversationSettings(enabled=False, retention_days=90, takeover_minutes=60, debounce_seconds=4, notify_email=True)
    return {"enabled": bool(s.enabled), "retention_days": s.retention_days, "takeover_minutes": s.takeover_minutes, "debounce_seconds": s.debounce_seconds, "notify_email": bool(s.notify_email),
            "limits": {"retention_days": [30, 365], "takeover_minutes": [5, 1440], "debounce_seconds": [2, 10]}}


def set_settings(db: Session, tenant: Tenant, user: User, *, enabled=None, retention_days=None, takeover_minutes=None, debounce_seconds=None, notify_email=None, ip: str | None = None) -> WhatsAppConversationSettings:
    s = get_settings(db, tenant.id, create=True)
    for name, val, lo, hi in (("retention_days", retention_days, 30, 365), ("takeover_minutes", takeover_minutes, 5, 1440), ("debounce_seconds", debounce_seconds, 2, 10)):
        if val is not None:
            if isinstance(val, bool) or not isinstance(val, int) or not lo <= val <= hi:
                raise WaError(422, "invalid_setting", f"Choose a whole number between {lo} and {hi}.")
            setattr(s, name, val)
    if enabled is not None:
        s.enabled = bool(enabled)
    if notify_email is not None:
        s.notify_email = bool(notify_email)
    db.flush()
    audit(db, action="whatsapp.conversation_settings", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_conversation_settings", entity_id=s.id,
          meta={"enabled": s.enabled, "retention_days": s.retention_days, "takeover_minutes": s.takeover_minutes, "debounce_seconds": s.debounce_seconds, "notify_email": s.notify_email}, ip=ip)
    return s


# ---- the window
def window_closes_at(conv: WhatsAppConversation) -> datetime | None:
    return conv.last_customer_message_at + WINDOW if conv.last_customer_message_at else None


def window_open(conv: WhatsAppConversation, now: datetime | None = None) -> bool:
    end = window_closes_at(conv)
    return end is not None and (now or utcnow()) < end


def needs_reply(conv: WhatsAppConversation) -> bool:
    """The customer's latest message has not been answered by anyone (a person, the assistant, an automatic message, or the owner on the WhatsApp Business app)."""
    return bool(conv.awaiting_reply)


def _paused(conv: WhatsAppConversation, now: datetime) -> bool:
    return conv.ai_paused_until is not None and conv.ai_paused_until > now


def _when(ts, now: datetime) -> datetime:
    """The time Meta says the message was sent, never in the future and never absurdly old."""
    try:
        t = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return now
    return now if t > now or t < now - timedelta(days=3) else t


# ---- finding and creating
def _code(db: Session, tenant_id: uuid.UUID) -> str:
    for _ in range(20):
        c = "C-" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(5))
        if db.scalar(select(WhatsAppConversation.id).where(WhatsAppConversation.tenant_id == tenant_id, WhatsAppConversation.code == c)) is None:
            return c
    return "C-" + secrets.token_hex(4).upper()


def get_or_create(db: Session, tenant_id: uuid.UUID, contact: WhatsAppContact) -> WhatsAppConversation:
    conv = db.scalar(select(WhatsAppConversation).where(WhatsAppConversation.tenant_id == tenant_id, WhatsAppConversation.contact_id == contact.id))
    if conv is None:
        conv = WhatsAppConversation(tenant_id=tenant_id, contact_id=contact.id, code=_code(db, tenant_id), status="open")
        db.add(conv)
        db.flush()
    return conv


def get(db: Session, tenant_id: uuid.UUID, conv_id: uuid.UUID) -> WhatsAppConversation:
    c = db.scalar(select(WhatsAppConversation).where(WhatsAppConversation.id == conv_id, WhatsAppConversation.tenant_id == tenant_id))
    if c is None:
        raise WaError(404, "not_found", "That conversation was not found.")
    return c


def _clean_text(text) -> str | None:
    if not isinstance(text, str):
        return None
    t = text.replace("\x00", "").strip()
    return t[: settings.whatsapp_conversation_text_max_chars] or None


def ingest(db: Session, tenant: Tenant, phone: str, msg: dict, now: datetime | None = None) -> dict | None:
    """A customer's message arrived on this business's verified number and is not STOP or an opt-in. Stores it, opens the 24-hour window, and starts the wait for more messages.
    Idempotent by Meta's message id. Returns None for a number that cannot be used, {"duplicate": True} for a repeat, otherwise the conversation to look at once the wait is over."""
    now = now or utcnow()
    try:
        p = consent.e164(phone)
    except WaError:
        return None
    wamid = (msg.get("id") or "").strip() or None
    if wamid and db.scalar(select(WhatsAppConversationMessage.id).where(WhatsAppConversationMessage.tenant_id == tenant.id, WhatsAppConversationMessage.meta_message_id == wamid)) is not None:
        return {"duplicate": True}
    contact, _ = consent.create_contact(db, tenant, phone=p, name=None, tags=[], source="customer_message", user_id=None)  # a contact is not consent: none is recorded
    when = _when(msg.get("timestamp"), now)
    conv = get_or_create(db, tenant.id, contact)
    stored_at = max(when, conv.last_message_at + timedelta(milliseconds=1)) if conv.last_message_at else when  # strictly after what is already there, so the order on screen is the order it happened
    kind = (msg.get("type") or "text")[:16]
    text = _clean_text(msg.get("text")) if kind in ("text", "button", "interactive") else None
    try:
        with db.begin_nested():
            db.add(WhatsAppConversationMessage(tenant_id=tenant.id, conversation_id=conv.id, direction="inbound", sender_type="customer", text=text, msg_type=kind, meta_message_id=wamid,
                                               delivery_status="received", created_at=stored_at))
            db.flush()
    except IntegrityError:
        return {"duplicate": True}
    conv.last_customer_message_at = max(conv.last_customer_message_at or when, when)
    conv.last_message_at = max(conv.last_message_at or stored_at, stored_at)
    conv.unread_count = (conv.unread_count or 0) + 1
    conv.awaiting_reply = True
    consent.note_reply(db, tenant, p, when)  # the time only
    if conv.status == "closed":
        conv.status, conv.handoff_reason = "open", None
    cs = get_settings(db, tenant.id)
    conv.reply_due_at = now + timedelta(seconds=cs.debounce_seconds if cs else 4)
    if contact.marketing_opted_out_at is not None or consent.is_suppressed(db, tenant.id, contact.phone):
        _mark_handoff(conv, "customer_opted_out", now)  # a customer who said STOP is never answered automatically
    db.flush()
    return {"conversation_id": conv.id, "debounce": cs.debounce_seconds if cs else 4}


def ingest_echo(db: Session, tenant: Tenant, to_phone: str, e: dict, now: datetime | None = None) -> bool:
    """A message the owner typed in the WhatsApp Business app on their phone, reported back by Meta (coexistence). UNVERIFIED against real Meta traffic (docs/WHATSAPP_META_CHECKLIST.md, first item).
    Only attached to a customer who already has a conversation; it counts as a person replying."""
    now = now or utcnow()
    try:
        p = consent.e164(to_phone)
    except WaError:
        return False
    contact = consent.find_by_phone(db, tenant.id, p)
    conv = db.scalar(select(WhatsAppConversation).where(WhatsAppConversation.tenant_id == tenant.id, WhatsAppConversation.contact_id == contact.id)) if contact else None
    if conv is None:
        return False
    wamid = (e.get("id") or "").strip() or None
    if wamid and db.scalar(select(WhatsAppConversationMessage.id).where(WhatsAppConversationMessage.tenant_id == tenant.id, WhatsAppConversationMessage.meta_message_id == wamid)) is not None:
        return False
    when = _when(e.get("timestamp"), now)
    when = max(when, conv.last_message_at + timedelta(milliseconds=1)) if conv.last_message_at else when
    kind = (e.get("type") or "text")[:16]
    try:
        with db.begin_nested():
            db.add(WhatsAppConversationMessage(tenant_id=tenant.id, conversation_id=conv.id, direction="outbound", sender_type="staff", staff_user_id=None, text=_clean_text(e.get("text")) if kind == "text" else None,
                                               msg_type=kind, meta_message_id=wamid, delivery_status="sent", via_app=True, created_at=when, sent_at=when))
            db.flush()
    except IntegrityError:
        return False
    cs = get_settings(db, tenant.id)
    conv.last_outbound_at, conv.last_message_at = max(conv.last_outbound_at or when, when), max(conv.last_message_at or when, when)
    conv.ai_paused_until = now + timedelta(minutes=cs.takeover_minutes if cs else 60)
    conv.unread_count, conv.awaiting_reply = 0, False
    if conv.status == "needs_human":
        conv.status, conv.handoff_reason = "open", None
    return True


def sync_status(db: Session, ledger: WhatsAppMessage) -> None:
    """A delivery update for a sent message also moves the matching conversation message forward."""
    row = db.scalar(select(WhatsAppConversationMessage).where(WhatsAppConversationMessage.ledger_id == ledger.id))
    if row is not None and ledger.delivery_status in ("sent", "delivered", "read", "failed"):
        row.delivery_status, row.error_code = ledger.delivery_status, (ledger.error_code if ledger.delivery_status == "failed" else row.error_code)


# ---- handoff, takeover, and the wait that ends
def _mark_handoff(conv: WhatsAppConversation, reason: str, now: datetime) -> None:
    changed = conv.status != "needs_human" or conv.handoff_reason != reason
    conv.status, conv.handoff_reason = "needs_human", reason
    if changed:
        conv.handoff_at = now


def handoff(db: Session, tenant: Tenant, conv: WhatsAppConversation, reason: str, now: datetime | None = None, *, notify: bool = True) -> None:
    """The conversation needs a person. Records why (the owner sees it) and tells the owner by email, at most once an hour per conversation."""
    now = now or utcnow()
    _mark_handoff(conv, reason if reason in rules.HANDOFF_WORDS else "send_blocked", now)
    if notify:
        notify_handoff(db, tenant, conv, now)


def _assistant():
    """Phase 8 plugs the assistant in here. Without it (or with it off) every conversation waits for a person."""
    try:
        from app.services.whatsapp import agent
    except ImportError:
        return None
    return agent


def handle_due(db: Session, tenant: Tenant, conv: WhatsAppConversation, now: datetime | None = None) -> str:
    """The wait for more messages from this customer has ended. If a person is already in the conversation, nothing more happens. Otherwise the assistant (if it is on and allowed) answers once;
    in every other case the conversation goes to a person with a reason."""
    now = now or utcnow()
    if conv.status == "closed" or not needs_reply(conv):
        return "nothing"
    if _paused(conv, now):
        return "person_is_handling"
    if conv.handoff_reason == "customer_opted_out":
        handoff(db, tenant, conv, "customer_opted_out", now)
        return "handoff"
    ai = _assistant()
    if ai is not None:
        outcome = ai.handle_due(db, tenant, conv, now)
        if outcome is not None:
            return outcome
    handoff(db, tenant, conv, "assistant_off", now)
    return "handoff"


def run_due(db: Session, now: datetime | None = None, limit: int = 50, tenant_id: uuid.UUID | None = None) -> dict:
    """The worker pass: every conversation whose wait is over. Rows are locked (SKIP LOCKED), so two workers never handle the same one. One broken conversation never stops the others."""
    now = now or utcnow()
    if not platform_on():
        return {"held": True}
    out = {"handled": 0, "handoff": 0, "replied": 0, "nothing": 0}
    q = select(WhatsAppConversation).where(WhatsAppConversation.reply_due_at.is_not(None), WhatsAppConversation.reply_due_at <= now)
    if tenant_id is not None:
        q = q.where(WhatsAppConversation.tenant_id == tenant_id)
    for conv in db.scalars(q.order_by(WhatsAppConversation.reply_due_at).limit(limit).with_for_update(skip_locked=True)):
        conv.reply_due_at = None
        tenant = db.get(Tenant, conv.tenant_id)
        if tenant is None or not enabled_for(db, tenant.id):
            continue
        try:
            with db.begin_nested():
                r = handle_due(db, tenant, conv, now)
        except Exception:  # noqa: BLE001 - never silence: a conversation that broke goes to a person
            log.exception("conversation %s failed", conv.id)
            r = "handoff"
            try:
                with db.begin_nested():
                    handoff(db, tenant, conv, "ai_unavailable", now)
            except Exception:  # noqa: BLE001
                log.exception("could not even hand off conversation %s", conv.id)
        out["handled"] += 1
        out[r if r in out else "nothing"] = out.get(r if r in out else "nothing", 0) + 1
    return out


def staff_reply(db: Session, tenant: Tenant, user: User, conv: WhatsAppConversation, text: str, *, confirm_marketing: bool = False, client_id: str | None = None, ip: str | None = None,
                now: datetime | None = None) -> dict:
    """A person replies, free-form, while the window is open. A message that looks like an offer needs the person to confirm once (logged). A person replying pauses the assistant."""
    now = now or utcnow()
    key = f"staff:{conv.id}:{(client_id or uuid.uuid4().hex)[:64]}"
    res = sender.send_service_reply(db, tenant, conv, text, sender_type="staff", staff_user=user, idem_key=key, marketing_confirmed=confirm_marketing, now=now)
    if res.status == "skipped" and res.reason == "marketing_warning":
        raise WaError(409, "marketing_warning", SEND_PROBLEMS["marketing_warning"][1], extra={"terms": rules.marketing_terms(text)})
    if res.status == "skipped":
        status, msg = SEND_PROBLEMS.get(res.reason, (409, "That message could not be sent."))
        raise WaError(status, res.reason, msg)
    if res.status == "retry":
        status, msg = SEND_PROBLEMS.get(res.reason, (503, "Please try again in a minute."))
        raise WaError(status, res.reason, msg)
    if res.status == "failed":
        raise WaError(502, "meta_rejected", SEND_PROBLEMS["meta_rejected"][1])
    cs = get_settings(db, tenant.id)
    conv.ai_paused_until = now + timedelta(minutes=cs.takeover_minutes if cs else 60)
    conv.assigned_to, conv.unread_count = user.id, 0
    if conv.status == "needs_human":
        conv.status, conv.handoff_reason = "open", None
    if confirm_marketing and rules.marketing_terms(text):
        audit(db, action="whatsapp.service_reply_marketing_confirmed", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_conversation", entity_id=conv.id,
              meta={"terms": rules.marketing_terms(text)[:5]}, ip=ip)  # what was confirmed, not the whole message
    return {"sent": True, "duplicate": res.reason == "duplicate", "ledger_id": res.message_id}


def take_over(db: Session, tenant: Tenant, user: User, conv: WhatsAppConversation, now: datetime | None = None) -> WhatsAppConversation:
    now = now or utcnow()
    cs = get_settings(db, tenant.id)
    conv.ai_paused_until = now + timedelta(minutes=cs.takeover_minutes if cs else 60)
    conv.assigned_to = user.id
    conv.status, conv.handoff_reason, conv.handoff_at = "open", "staff_took_over", now
    return conv


def hand_back(db: Session, tenant: Tenant, user: User, conv: WhatsAppConversation, now: datetime | None = None) -> WhatsAppConversation:
    """Let the assistant answer again. If the customer is waiting, it looks at the conversation after the usual short wait."""
    now = now or utcnow()
    conv.ai_paused_until, conv.assigned_to = None, None
    if conv.handoff_reason != "customer_opted_out":  # a person handing back clears the reason; a customer who sent STOP is never answered by the assistant whatever is pressed (checked again at answer time)
        conv.handoff_reason = None
        if conv.status == "needs_human":
            conv.status = "open"
    if needs_reply(conv):
        cs = get_settings(db, tenant.id)
        conv.reply_due_at = now + timedelta(seconds=cs.debounce_seconds if cs else 4)
    return conv


def mark_read(conv: WhatsAppConversation) -> None:
    conv.unread_count = 0


def close(conv: WhatsAppConversation) -> None:
    conv.status, conv.handoff_reason, conv.reply_due_at, conv.unread_count, conv.awaiting_reply = "closed", None, None, 0, False


def reopen(conv: WhatsAppConversation) -> None:
    conv.status = "open"


def delete_conversation(db: Session, tenant: Tenant, user: User, conv: WhatsAppConversation, ip: str | None = None) -> None:
    cid = conv.id
    db.delete(conv)
    db.flush()
    audit(db, action="whatsapp.conversation_delete", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_conversation", entity_id=cid, ip=ip)


# ---- telling a person
def notify_handoff(db: Session, tenant: Tenant, conv: WhatsAppConversation, now: datetime | None = None) -> int:
    """Email the owner and admins that a conversation needs a person. At most one email an hour per conversation. The email carries no message text: just who and a link."""
    now = now or utcnow()
    cs = get_settings(db, tenant.id)
    if cs is None or not cs.notify_email:
        return 0
    if conv.last_notified_at is not None and now - conv.last_notified_at < NOTIFY_GAP:
        return 0
    conv.last_notified_at = now
    contact = db.get(WhatsAppContact, conv.contact_id)
    who = (contact.customer_name if contact and contact.customer_name else "A customer")
    reason = rules.HANDOFF_WORDS.get(conv.handoff_reason or "", "It is waiting for a person.")
    link = f"{settings.frontend_url.rstrip('/')}/whatsapp/inbox?c={conv.id}"
    n = 0
    for user in db.scalars(select(User).join(Membership, Membership.user_id == User.id).where(Membership.tenant_id == tenant.id, Membership.role.in_([Role.owner, Role.admin]))):
        if not user.is_active or not user.email or user.email_verified_at is None:
            continue
        mailer.send_email(user.email, f"FlowQR: a WhatsApp conversation needs you at {tenant.name}",
                          f"Hi {user.full_name.split()[0] if user.full_name else ''},\n\n{who} wrote to {tenant.name} on WhatsApp and the conversation needs a person.\n{reason}\n\nOpen the inbox: {link}\n\n"
                          "The message itself is not in this email. You can turn these emails off in the inbox settings.")
        n += 1
    return n


# ---- reading
def _name(c: WhatsAppContact | None) -> str:
    return (c.customer_name if c and c.customer_name else None) or "A customer"


def serialize_message(m: WhatsAppConversationMessage, contact: WhatsAppContact | None, staff: dict[uuid.UUID, str]) -> dict:
    label = {"customer": _name(contact), "ai": "Assistant (automated)", "system": "Automatic message"}.get(m.sender_type)
    if m.sender_type == "staff":
        label = "WhatsApp Business app" if m.via_app else (staff.get(m.staff_user_id) or "A team member")
    return {"id": m.id, "direction": m.direction, "sender_type": m.sender_type, "sender_label": label, "text": m.text, "msg_type": m.msg_type, "status": m.delivery_status, "created_at": m.created_at,
            "template_key": m.template_key, "via_app": m.via_app, "marketing_confirmed": m.marketing_confirmed, "error_code": m.error_code}


def _staff_names(db: Session, ids: set) -> dict[uuid.UUID, str]:
    ids = {i for i in ids if i}
    return {u.id: (u.full_name or u.email) for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}


def summary(db: Session, conv: WhatsAppConversation, contact: WhatsAppContact | None, now: datetime | None = None) -> dict:
    now = now or utcnow()
    last = db.scalar(select(WhatsAppConversationMessage).where(WhatsAppConversationMessage.conversation_id == conv.id).order_by(WhatsAppConversationMessage.created_at.desc()).limit(1))
    preview = None
    if last is not None:
        preview = (last.text or f"[{last.msg_type}]")[:120]
    c_state = None
    if contact is not None:
        c_state = {"id": contact.id, "name": contact.customer_name, "phone": contact.phone, "source": contact.source, "opted_out": contact.marketing_opted_out_at is not None,
                   "no_consent": contact.source == "customer_message" and consent.active_consent(db, contact.id, "marketing") is None and consent.active_consent(db, contact.id, "utility") is None
                   and consent.active_consent(db, contact.id, "occasion") is None}
    return {"id": conv.id, "contact": c_state, "status": conv.status, "handoff_reason": conv.handoff_reason, "handoff_words": rules.HANDOFF_WORDS.get(conv.handoff_reason or ""), "unread": conv.unread_count,
            "needs_reply": needs_reply(conv), "preview": preview, "preview_from": last.sender_type if last else None, "last_message_at": conv.last_message_at, "window_open": window_open(conv, now),
            "window_closes_at": window_closes_at(conv), "ai_paused_until": conv.ai_paused_until if conv.ai_paused_until and conv.ai_paused_until > now else None, "assigned_to": conv.assigned_to,
            "source": conv.source, "ai_off": conv.ai_off}


def list_conversations(db: Session, tenant_id: uuid.UUID, *, q: str | None = None, filter: str = "all", limit: int = PAGE, offset: int = 0, now: datetime | None = None) -> dict:
    now = now or utcnow()
    base = select(WhatsAppConversation, WhatsAppContact).join(WhatsAppContact, WhatsAppContact.id == WhatsAppConversation.contact_id).where(WhatsAppConversation.tenant_id == tenant_id)
    if filter == "closed":
        base = base.where(WhatsAppConversation.status == "closed")
    else:
        base = base.where(WhatsAppConversation.status != "closed")
        if filter == "needs_you":
            base = base.where(or_(WhatsAppConversation.status == "needs_human", WhatsAppConversation.unread_count > 0))
        elif filter == "unread":
            base = base.where(WhatsAppConversation.unread_count > 0)
    if q and q.strip():
        term = q.strip()
        like = "%" + term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        digits = re.sub(r"\D", "", term)
        conds = [WhatsAppContact.customer_name.ilike(like, escape="\\"), exists().where(WhatsAppConversationMessage.conversation_id == WhatsAppConversation.id, WhatsAppConversationMessage.text.ilike(like, escape="\\"))]
        if len(digits) >= 3:
            conds.append(WhatsAppContact.phone.like(f"%{digits}%"))
        base = base.where(or_(*conds))
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(base.order_by(WhatsAppConversation.last_message_at.desc().nullslast(), WhatsAppConversation.created_at.desc()).limit(max(1, min(limit, 100))).offset(max(0, offset))).all()
    unread_total = db.scalar(select(func.coalesce(func.sum(WhatsAppConversation.unread_count), 0)).where(WhatsAppConversation.tenant_id == tenant_id, WhatsAppConversation.status != "closed")) or 0
    waiting = db.scalar(select(func.count()).select_from(WhatsAppConversation).where(WhatsAppConversation.tenant_id == tenant_id, WhatsAppConversation.status == "needs_human")) or 0
    return {"total": total, "unread_total": int(unread_total), "needs_you": waiting, "items": [summary(db, c, ct, now) for c, ct in rows]}


def thread(db: Session, tenant: Tenant, conv: WhatsAppConversation, *, before: datetime | None = None, limit: int = 100, now: datetime | None = None) -> dict:
    now = now or utcnow()
    contact = db.get(WhatsAppContact, conv.contact_id)
    q = select(WhatsAppConversationMessage).where(WhatsAppConversationMessage.conversation_id == conv.id)
    if before is not None:
        q = q.where(WhatsAppConversationMessage.created_at < before)
    msgs = list(reversed(list(db.scalars(q.order_by(WhatsAppConversationMessage.created_at.desc()).limit(max(1, min(limit, 200)))))))
    names = _staff_names(db, {m.staff_user_id for m in msgs} | {conv.assigned_to})
    out = summary(db, conv, contact, now)
    out["messages"] = [serialize_message(m, contact, names) for m in msgs]
    ai_ids = [m.id for m in msgs if m.sender_type == "ai"]
    if ai_ids:
        from app.services.whatsapp import agent
        fb = agent.feedback_for(db, conv.id, ai_ids)
        for m in out["messages"]:
            if m["id"] in fb:
                m["feedback"], m["model_version"] = fb[m["id"]]["feedback"], fb[m["id"]]["model_version"]
    out["ai_off"] = conv.ai_off
    out["assigned_name"] = names.get(conv.assigned_to)
    out["code"] = conv.code
    out["fallback_templates"] = [] if window_open(conv, now) else fallback_templates(db, tenant, contact)
    out["window_note"] = None if window_open(conv, now) else ("WhatsApp only allows an approved message now: the customer's 24-hour window has closed." if conv.last_customer_message_at else "This customer has not written to you.")
    return out


def fallback_templates(db: Session, tenant: Tenant, contact: WhatsAppContact | None) -> list[dict]:
    """Outside the window only an approved message can go. Offered only if it exists, is approved and the customer agreed to updates."""
    row = templates.standard_row(db, tenant.id, FALLBACK_TEMPLATE)
    reason = None
    if contact is None:
        reason = "no_customer"
    elif row is None or row.approval_status != "approved":
        reason = "template_not_approved"
    elif consent.active_consent(db, contact.id, "utility") is None:
        reason = "no_utility_consent"
    return [{"key": FALLBACK_TEMPLATE, "label": "Follow up on their enquiry", "can_send": reason is None, "reason": reason,
             "text": templates.render(row, ["there", tenant.name]) if row is not None and row.body_text else None}]


def send_fallback_template(db: Session, tenant: Tenant, user: User, conv: WhatsAppConversation, key: str, *, client_id: str | None = None, now: datetime | None = None) -> dict:
    now = now or utcnow()
    if key != FALLBACK_TEMPLATE:
        raise WaError(422, "invalid_template", "Choose one of the offered messages.")
    if window_open(conv, now):
        raise WaError(409, "window_open", "The window is open: write a reply instead.")
    contact = db.get(WhatsAppContact, conv.contact_id)
    row = templates.standard_row(db, tenant.id, key)
    if contact is None or row is None:
        raise WaError(409, "template_not_approved", "That message is not ready.")
    res = sender.send_template(db, tenant, contact, row, [templates.first_name(contact.customer_name), tenant.name], idem_key=f"convtpl:{conv.id}:{(client_id or uuid.uuid4().hex)[:64]}")
    if res.status != "sent":
        words = {"no_utility_consent": "This customer has not agreed to updates about their enquiry.", "template_not_approved": "WhatsApp has not approved that message yet.", "opted_out": "This customer asked to stop."}
        raise WaError(409, res.reason, words.get(res.reason, "That message could not be sent."))
    body = templates.render(row, [templates.first_name(contact.customer_name), tenant.name])
    db.add(WhatsAppConversationMessage(tenant_id=tenant.id, conversation_id=conv.id, direction="outbound", sender_type="staff", staff_user_id=user.id, text=body, template_key=key, ledger_id=res.message_id,
                                       delivery_status="sent", sent_at=now))
    conv.last_outbound_at = conv.last_message_at = now
    conv.assigned_to, conv.unread_count, conv.awaiting_reply = user.id, 0, False
    return {"sent": True}


# ---- retention: message text is kept for the business's chosen period, then deleted
def purge(db: Session, now: datetime | None = None) -> dict:
    """Delete conversation text older than each business's retention period, then conversations left empty, then contacts that only ever existed because they wrote to us (no consent of any kind,
    never opted out) and have no conversation left. Counts only; nothing about content is logged."""
    now = now or utcnow()
    total = {"messages": 0, "conversations": 0, "contacts": 0}
    for cs in db.scalars(select(WhatsAppConversationSettings)):
        cutoff = now - timedelta(days=cs.retention_days)
        m = db.execute(delete(WhatsAppConversationMessage).where(WhatsAppConversationMessage.tenant_id == cs.tenant_id, WhatsAppConversationMessage.created_at < cutoff)).rowcount or 0
        c = db.execute(delete(WhatsAppConversation).where(WhatsAppConversation.tenant_id == cs.tenant_id, WhatsAppConversation.created_at < cutoff,
                                                         ~exists().where(WhatsAppConversationMessage.conversation_id == WhatsAppConversation.id))).rowcount or 0
        orphan = select(WhatsAppContact.id).where(WhatsAppContact.tenant_id == cs.tenant_id, WhatsAppContact.source == "customer_message", WhatsAppContact.marketing_opted_out_at.is_(None),
                                                  WhatsAppContact.created_at < cutoff, ~exists().where(WhatsAppConsent.contact_id == WhatsAppContact.id),
                                                  ~exists().where(WhatsAppConversation.contact_id == WhatsAppContact.id))
        from app.models.whatsapp import WhatsAppBooking
        orphan = orphan.where(~exists().where(WhatsAppBooking.contact_id == WhatsAppContact.id))  # someone with a booking is not just a stranger who wrote once
        for hook in _CONTACT_KEEPERS:  # later features (bookings) add their own reasons to keep a contact
            orphan = orphan.where(~hook(WhatsAppContact.id))
        k = db.execute(delete(WhatsAppContact).where(WhatsAppContact.id.in_(orphan))).rowcount or 0
        if m or c or k:
            audit(db, action="whatsapp.conversation_purge", tenant_id=cs.tenant_id, meta={"messages": m, "conversations": c, "contacts": k, "retention_days": cs.retention_days})
        total["messages"] += m
        total["conversations"] += c
        total["contacts"] += k
    from app.services.whatsapp import agent
    ai = agent.purge(db, now)
    total["ai_questions"], total["ai_runs"] = ai["questions"], ai["runs"]
    return total


_CONTACT_KEEPERS: list = []  # callables(contact_id_column) -> a SQL condition that is true when something else (a booking) still needs the contact
