"""The ONE place a WhatsApp message is sent. Every automation and every campaign goes through `send_template`; nothing else calls Meta's send API.

A send happens only if ALL of these hold (the first failure is the answer, as a stable reason code):
  1. platform switches: WhatsApp on, no emergency stop, sending enabled (gate.preflight);
  2. the business has the add-on and a healthy connection of ITS OWN, and the customer has the consent the template's real category needs, with no opt-out (gate.preflight);
  3. the template is approved, belongs to this business's connection, and is a marketing or utility template;
  4. the variables are short single-line text and match the template;
  5. this idempotency key has not already sent (a retry, a re-run or two workers can never send twice);
  6. a marketing message is not too soon after another to the same person;
  7. the business is within its per-minute and per-day limits.
Only approved TEMPLATES are ever sent, never free text, so Meta's 24-hour customer-service window rules do not need to be relied on. A retryable Meta failure leaves no trace (the caller retries
with the same key); a final failure is recorded on the message with Meta's error code.
"""
import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import hit
from app.models import Tenant
from app.models.base import utcnow
from app.models.whatsapp import WhatsAppContact, WhatsAppMessage, WhatsAppTemplate
from app.services.whatsapp import connection, gate, pricing
from app.services.whatsapp.meta import MetaError, get_meta_client
from app.services.whatsapp.templates import clean_variable, placeholders

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


GAP_EXEMPT = ("optin_confirm", "occasion")  # not offers: a confirmation the customer just asked for, and (later) greetings, which have their own cap


def send_template(db: Session, tenant: Tenant, contact: WhatsAppContact, template: WhatsAppTemplate, variables: list[str], *, idem_key: str, run_id: uuid.UUID | None = None,
                  campaign_id: uuid.UUID | None = None, kind: str | None = None) -> SendResult:
    purpose = template.category
    if purpose not in SENDABLE:
        return _skip("category_not_supported")
    ok, reason = gate.preflight(db, tenant.id, contact, purpose)
    if not ok:
        return _skip(reason)
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
    rate = pricing.rate_for(db, purpose)
    msg = WhatsAppMessage(tenant_id=tenant.id, connection_id=conn.id, contact_id=contact.id, phone_number_id=conn.phone_number_id, direction="outbound", category=purpose, template_id=template.id,
                          delivery_status="queued", idempotency_key=idem_key, run_id=run_id, campaign_id=campaign_id, est_rate=rate.rate if rate else None, kind=kind)
    try:
        with db.begin_nested():
            db.add(msg)
            db.flush()
    except IntegrityError:  # another worker took this key a moment ago
        return SendResult("sent", "duplicate")
    now = utcnow()
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
