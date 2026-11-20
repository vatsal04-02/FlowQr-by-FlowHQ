"""The ONE place a WhatsApp message is sent. Every automation and every campaign goes through `send_template`; nothing else calls Meta's send API.

A send happens only if ALL of these hold (the first failure is the answer, as a stable reason code):
  1. platform switches: WhatsApp on, no emergency stop, sending enabled (gate.preflight);
  2. the business has the add-on and a healthy connection of ITS OWN, and the customer has the consent the template's real category needs, with no opt-out (gate.preflight);
  3. the template is approved, belongs to this business's connection, and is a marketing or utility template;
  4. the variables are short single-line text and match the template;
  5. this idempotency key has not already sent (a retry, a re-run or two workers can never send twice);
  6. a marketing message is not too soon after another to the same person;
  7. the business is within its per-minute and per-day limits;
  8. a birthday or festival greeting (kind "occasion") also needs: the Growth or Pro add-on, its own greeting template, occasion consent (and offers consent while the template's category is marketing or
     not yet known; STOP always blocks it), 9 am to 9 pm India time, and at least WHATSAPP_OCCASION_GAP_DAYS since the last greeting to that person. Greetings are not offers: the offer gap does not apply to them.
Only approved TEMPLATES are sent by send_template, so Meta's 24-hour customer-service window rules do not need to be relied on there. The ONE exception is `send_service_reply` at the end of this file:
a free-form reply to a customer who wrote first, sent only while their 24-hour window is open (see its docstring for every condition). A retryable Meta failure leaves no trace (the caller retries
with the same key); a final failure is recorded on the message with Meta's error code.
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import hit
from app.models import Tenant
from app.models.base import utcnow
from app.models.whatsapp import WhatsAppContact, WhatsAppMessage, WhatsAppTemplate
from app.services.whatsapp import addons, connection, gate, pricing, rules
from app.services.whatsapp.meta import MetaError, get_meta_client
from app.services.whatsapp.templates import clean_variable, key_of, placeholders

log = logging.getLogger("flowqr.whatsapp.sender")
SENDABLE = ("marketing", "utility")
TOKEN_ERRORS = {190, 102, 10}  # Meta: invalid or expired access token, session, permission


@dataclass
class SendResult:
    status: str  # sent | skipped | failed | retry
    reason: str = "ok"
    message_id: uuid.UUID | None = None
    retry_after: int = 0

    @property
    def ok(self) -> bool:
        return self.status == "sent"


def _skip(reason: str) -> SendResult:
    return SendResult("skipped", reason)


GAP_EXEMPT = ("optin_confirm", "occasion")  # not offers: a confirmation the customer just asked for, and greetings, which have their own cap
# A kind that is exempt from the offer gap may only be used with its own messages, so no offer can ever be sent under a kind that skips the offer rules.
KIND_TEMPLATES = {"optin_confirm": ("optin_confirm", "optin_confirm_offers"), "occasion": ("occasion_birthday", "occasion_festival")}


def send_template(db: Session, tenant: Tenant, contact: WhatsAppContact, template: WhatsAppTemplate, variables: list[str], *, idem_key: str, run_id: uuid.UUID | None = None,
                  campaign_id: uuid.UUID | None = None, kind: str | None = None, now: datetime | None = None) -> SendResult:
    now = now or utcnow()
    purpose = template.category
    if purpose not in SENDABLE:
        return _skip("category_not_supported")
    if kind is not None and (kind not in KIND_TEMPLATES or key_of(template.template_name) not in KIND_TEMPLATES[kind]):
        return _skip("kind_mismatch")
    ok, reason = gate.preflight(db, tenant.id, contact, purpose, template=template, kind=kind)
    if not ok:
        return _skip(reason)
    if kind == "occasion":
        if not addons.occasions_allowed(db, tenant.id):
            return _skip("plan_required")
        if not rules.in_occasion_hours(now):
            return _skip("outside_hours")
        since_g = now - timedelta(days=settings.whatsapp_occasion_gap_days)
        if db.scalar(select(WhatsAppMessage.id).where(WhatsAppMessage.tenant_id == tenant.id, WhatsAppMessage.contact_id == contact.id, WhatsAppMessage.kind == "occasion",
                                                       WhatsAppMessage.delivery_status != "failed", WhatsAppMessage.created_at >= since_g).limit(1)) is not None:
            return _skip("greeting_too_soon")
    conn = connection.connected_connection(db, tenant.id)
    if template.tenant_id != tenant.id or conn is None or template.connection_id != conn.id:
        return _skip("template_mismatch")
    if template.approval_status != "approved":
        return _skip("template_not_approved")
    params = [clean_variable(v) for v in variables]
    if len(params) != max(placeholders(template.body_text), len(template.variable_schema or [])) or any(not p for p in params):
        return _skip("invalid_variables")
    existing = db.scalar(select(WhatsAppMessage).where(WhatsAppMessage.tenant_id == tenant.id, WhatsAppMessage.idempotency_key == idem_key))
    if existing is not None:
        return SendResult("sent" if existing.delivery_status != "failed" else "failed", "duplicate", existing.id)
    if purpose == "marketing" and kind not in GAP_EXEMPT:
        since = utcnow() - timedelta(hours=settings.whatsapp_marketing_gap_hours)
        recent = db.scalar(select(WhatsAppMessage.id).where(WhatsAppMessage.tenant_id == tenant.id, WhatsAppMessage.contact_id == contact.id, WhatsAppMessage.category == "marketing",
                                                           WhatsAppMessage.delivery_status != "failed", WhatsAppMessage.created_at >= since,
                                                           or_(WhatsAppMessage.kind.is_(None), WhatsAppMessage.kind.not_in(GAP_EXEMPT))).limit(1))
        if recent is not None:
            return _skip("too_soon")
    if not hit(f"wa-send-min:{tenant.id}", settings.whatsapp_send_per_minute, 60):
        return SendResult("retry", "rate_limited", retry_after=60)
    if not hit(f"wa-send-day:{tenant.id}", settings.whatsapp_daily_cap, 86400):
        return SendResult("retry", "daily_cap", retry_after=3600)
    token = connection._token_of(conn)  # noqa: SLF001
    if not token:
        return _skip("not_connected")
    est = pricing.est_rate_for_send(db, tenant.id, purpose)
    msg = WhatsAppMessage(tenant_id=tenant.id, connection_id=conn.id, contact_id=contact.id, phone_number_id=conn.phone_number_id, direction="outbound", category=purpose, template_id=template.id,
                          delivery_status="queued", idempotency_key=idem_key, run_id=run_id, campaign_id=campaign_id, est_rate=est, kind=kind)
    try:
        with db.begin_nested():
            db.add(msg)
            db.flush()
    except IntegrityError:  # another worker took this key a moment ago
        return SendResult("sent", "duplicate")
    now = utcnow()  # the moment of sending (not the pretend "now" a test may have passed in)
    try:
        wamid = get_meta_client().send_template(token, conn.phone_number_id, contact.phone, template.template_name, template.language, params)
    except MetaError as exc:
        if exc.retryable:
            db.delete(msg)  # no trace: the retry uses the same key
            db.flush()
            return SendResult("retry", "meta_unavailable", retry_after=120)
        msg.delivery_status, msg.error_code, msg.status_updated_at = "failed", str(exc.code or exc.status or "meta")[:20], now
        if exc.code in TOKEN_ERRORS:
            conn.status, conn.attention_reason = "needs_attention", "Meta no longer accepts this connection. Press Connect WhatsApp to connect again."
        db.flush()
        log.warning("WhatsApp send refused by Meta (code %s)", exc.code)
        return SendResult("failed", "meta_rejected", msg.id)
    msg.meta_message_id, msg.delivery_status, msg.sent_at, msg.status_updated_at = wamid, "sent", now, now
    db.flush()
    return SendResult("sent", "ok", msg.id)


def send_service_reply(db: Session, tenant: Tenant, conv, text: str, *, sender_type: str, staff_user=None, idem_key: str, marketing_confirmed: bool = False, template_key: str | None = None,
                       now: datetime | None = None) -> SendResult:
    """A free-form reply inside a conversation (kind "service_reply"). The only place free-form text is ever sent. It is sent only when ALL of these hold, and the first failure is the answer:
      * the text is not empty and not too long;
      * the platform switch for conversations is on and this business has its inbox on;
      * the same switches as every message: WhatsApp on, no emergency stop, sending on, the add-on, a healthy connection from THIS business;
      * the customer wrote to the business first (`last_customer_message_at`) and that was less than 24 hours ago: outside the window only approved templates can be sent;
      * the text is not an offer, a discount or marketing. For the assistant and automatic messages that is a hard block. For a person it is a warning that they must confirm once, and the
        confirmation is recorded on the message (the caller also logs it);
      * this exact reply was not already sent (idempotency key), and the business is within its per-minute and per-day limits.
    It never touches consent: a customer writing to us gives no offers consent, and replying creates none. It is recorded in the message ledger with category "service" so the cost estimate (and the
    free monthly allowance) applies."""
    from app.models.whatsapp import WhatsAppContact, WhatsAppConversationMessage, WhatsAppConversationSettings
    now = now or utcnow()
    text = (text or "").strip()
    if not text or len(text) > settings.whatsapp_service_reply_max_chars or sender_type not in ("ai", "staff", "system"):
        return _skip("invalid_text")
    if not settings.whatsapp_conversations_enabled:
        return _skip("conversations_disabled")
    cs = db.scalar(select(WhatsAppConversationSettings).where(WhatsAppConversationSettings.tenant_id == tenant.id))
    if cs is None or not cs.enabled:
        return _skip("conversations_disabled")
    contact = db.get(WhatsAppContact, conv.contact_id)
    if contact is None or conv.tenant_id != tenant.id or contact.tenant_id != tenant.id:
        return _skip("wrong_business")
    ok, reason = gate.preflight(db, tenant.id, contact, "service", kind="service_reply")
    if not ok:
        return _skip(reason)
    conn = connection.connected_connection(db, tenant.id)
    if conn is None:
        return _skip("not_connected")
    if conv.last_customer_message_at is None:
        return _skip("no_customer_message")
    if now >= conv.last_customer_message_at + timedelta(hours=24):
        return _skip("window_closed")
    if rules.marketing_terms(text) and not (sender_type == "staff" and marketing_confirmed):
        return _skip("marketing_warning" if sender_type == "staff" else "marketing_content")
    existing = db.scalar(select(WhatsAppMessage).where(WhatsAppMessage.tenant_id == tenant.id, WhatsAppMessage.idempotency_key == idem_key))
    if existing is not None:
        return SendResult("sent" if existing.delivery_status != "failed" else "failed", "duplicate", existing.id)
    if not hit(f"wa-send-min:{tenant.id}", settings.whatsapp_send_per_minute, 60):
        return SendResult("retry", "rate_limited", retry_after=60)
    if not hit(f"wa-send-day:{tenant.id}", settings.whatsapp_daily_cap, 86400):
        return SendResult("retry", "daily_cap", retry_after=3600)
    token = connection._token_of(conn)  # noqa: SLF001
    if not token:
        return _skip("not_connected")
    msg = WhatsAppMessage(tenant_id=tenant.id, connection_id=conn.id, contact_id=contact.id, phone_number_id=conn.phone_number_id, direction="outbound", category="service", template_id=None,
                          delivery_status="queued", idempotency_key=idem_key, est_rate=pricing.est_rate_for_send(db, tenant.id, "service"), kind="service_reply")
    try:
        with db.begin_nested():
            db.add(msg)
            db.flush()
    except IntegrityError:
        return SendResult("sent", "duplicate")
    sent_at = utcnow()  # the moment of sending (not the pretend "now" a test may have passed in)

    def _record(status: str, wamid: str | None = None, code: str | None = None) -> None:
        db.add(WhatsAppConversationMessage(tenant_id=tenant.id, conversation_id=conv.id, direction="outbound", sender_type=sender_type, staff_user_id=getattr(staff_user, "id", None), text=text,
                                           meta_message_id=wamid, ledger_id=msg.id, delivery_status=status, error_code=code, template_key=template_key, marketing_confirmed=bool(marketing_confirmed and sender_type == "staff"),
                                           sent_at=sent_at if status != "failed" else None))
        conv.last_outbound_at, conv.last_message_at, conv.awaiting_reply = sent_at, sent_at, False

    try:
        wamid = get_meta_client().send_text(token, conn.phone_number_id, contact.phone, text)
    except MetaError as exc:
        if exc.retryable:
            db.delete(msg)  # no trace: the caller retries with the same key
            db.flush()
            return SendResult("retry", "meta_unavailable", retry_after=120)
        msg.delivery_status, msg.error_code, msg.status_updated_at = "failed", str(exc.code or exc.status or "meta")[:20], sent_at
        if exc.code in TOKEN_ERRORS:
            conn.status, conn.attention_reason = "needs_attention", "Meta no longer accepts this connection. Press Connect WhatsApp to connect again."
        _record("failed", None, msg.error_code)
        db.flush()
        log.warning("WhatsApp service reply refused by Meta (code %s)", exc.code)
        return SendResult("failed", "meta_rejected", msg.id)
    msg.meta_message_id, msg.delivery_status, msg.sent_at, msg.status_updated_at = wamid, "sent", sent_at, sent_at
    _record("sent", wamid)
    db.flush()
    return SendResult("sent", "ok", msg.id)
