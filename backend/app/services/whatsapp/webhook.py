"""The Meta webhook: verification, signature check, sanitised persistence, de-duplication and asynchronous processing.

Security properties (each has a test):
* The verification challenge needs the exact verify token (constant-time compare) and answers only the challenge, as text.
* A delivery is accepted only if `X-Hub-Signature-256` equals HMAC-SHA256(app secret, the RAW body). Anything else is refused BEFORE the body is parsed or stored.
* The tenant is NEVER taken from the payload. It is looked up from the verified `phone_number_id` through `whatsapp_connections`; an unknown or disconnected number is ignored and creates nothing.
* The stored body is sanitised (no profile names, no message text beyond what the opt-out rule needs, no media), and keyed by the SHA-256 of the raw body: a redelivery is recognised and not processed twice.
* Processing is idempotent: a status only ever moves forward, an opt-out is a no-op the second time.
"""
import hashlib
import hmac
import json
import logging
import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import constant_time_equals
from app.models import Tenant
from app.models.base import utcnow
from app.models.whatsapp import WhatsAppConnection, WhatsAppMessage, WhatsAppWebhookEvent
from app.services.whatsapp import consent, rules

log = logging.getLogger("flowqr.whatsapp.webhook")
MAX_BODY = 1_000_000
RANK = {"queued": 0, "sent": 1, "delivered": 2, "read": 3}
CODE_FORM = re.compile(r"\bCode:\s*[A-Za-z0-9]{6}\s*$", re.IGNORECASE)  # phones change letter case; the match itself ignores case too
ATTENTION_EVENTS = {"DISABLED_UPDATE", "ACCOUNT_VIOLATION", "ACCOUNT_RESTRICTION", "PARTNER_REMOVED", "ACCOUNT_DELETED"}


def verify_challenge(mode: str | None, token: str | None, challenge: str | None) -> str | None:
    expected = settings.whatsapp_webhook_verify_token
    if mode == "subscribe" and expected and token and constant_time_equals(token, expected) and challenge:
        return challenge[:200]
    return None


def signature_ok(raw: bytes, header: str | None) -> bool:
    secret = settings.meta_app_secret
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header[len("sha256="):].strip().lower())


def _digits(v, limit=15) -> str | None:
    d = re.sub(r"\D", "", str(v or ""))
    return d[:limit] if d else None


def sanitize(payload: dict) -> dict | None:
    """Reduce a Meta delivery to what Phase 1 uses. None = not a WhatsApp Business Account delivery."""
    if not isinstance(payload, dict) or payload.get("object") != "whatsapp_business_account" or not isinstance(payload.get("entry"), list):
        return None
    items = []
    for entry in payload["entry"][:20]:
        for ch in (entry.get("changes") or [])[:50] if isinstance(entry, dict) else []:
            if not isinstance(ch, dict) or not isinstance(ch.get("value"), dict):
                continue
            v = ch["value"]
            meta = v.get("metadata") if isinstance(v.get("metadata"), dict) else {}
            item = {"field": str(ch.get("field", ""))[:40], "waba_id": str(entry.get("id", ""))[:40], "phone_number_id": str(meta.get("phone_number_id", ""))[:40] or None, "statuses": [], "messages": []}
            for s in (v.get("statuses") or [])[:200]:
                if isinstance(s, dict) and s.get("id") and s.get("status"):
                    errs = [{"code": str(e.get("code", ""))[:12]} for e in (s.get("errors") or [])[:3] if isinstance(e, dict)]
                    item["statuses"].append({"id": str(s["id"])[:120], "status": str(s["status"])[:12], "timestamp": str(s.get("timestamp", ""))[:12], "errors": errs})
            for m in (v.get("messages") or [])[:200]:
                if isinstance(m, dict) and m.get("from"):
                    text = (m.get("text") or {}).get("body") if m.get("type") == "text" and isinstance(m.get("text"), dict) else None
                    keep = isinstance(text, str) and (len(text) <= 64 or (len(text) <= 240 and CODE_FORM.search(text)))  # an opt-in message carries a code; anything else long is not kept
                    item["messages"].append({"from": _digits(m["from"]), "id": str(m.get("id", ""))[:120], "type": str(m.get("type", ""))[:16], "text": text if keep else None, "timestamp": str(m.get("timestamp", ""))[:12]})
            if item["field"] == "account_update":
                item["event"] = str(v.get("event", ""))[:40]
            items.append(item)
    return {"items": items}


def receive(db: Session, raw: bytes) -> tuple[uuid.UUID | None, bool]:
    """Store a verified delivery. Returns (event_id, is_new); a redelivery of the same body returns (existing_id, False). Raises ValueError for a body that is not a WhatsApp delivery."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError("not json") from None
    clean = sanitize(payload)
    if clean is None:
        raise ValueError("not a WhatsApp delivery")
    digest = hashlib.sha256(raw).hexdigest()
    existing = db.scalar(select(WhatsAppWebhookEvent.id).where(WhatsAppWebhookEvent.payload_sha256 == digest))
    if existing:
        return existing, False
    first = next((i["phone_number_id"] for i in clean["items"] if i["phone_number_id"]), None)
    ev = WhatsAppWebhookEvent(payload_sha256=digest, phone_number_id=first, payload=clean, status="received", received_at=utcnow())
    try:
        with db.begin_nested():
            db.add(ev)
            db.flush()
    except IntegrityError:  # two identical deliveries raced: the other one won
        return db.scalar(select(WhatsAppWebhookEvent.id).where(WhatsAppWebhookEvent.payload_sha256 == digest)), False
    return ev.id, True


def enqueue(event_id: uuid.UUID) -> None:
    """Hand the event to the worker. If the broker is down the event stays `received` and the hourly housekeeping picks it up; the webhook must still answer 200."""
    try:
        from app.workers.tasks import whatsapp_process_event
        whatsapp_process_event.delay(str(event_id))
    except Exception:  # noqa: BLE001
        log.warning("could not queue WhatsApp event %s; housekeeping will retry", event_id)


def _connection_for(db: Session, phone_number_id: str | None) -> WhatsAppConnection | None:
    if not phone_number_id:
        return None
    return db.scalar(select(WhatsAppConnection).where(WhatsAppConnection.phone_number_id == phone_number_id, WhatsAppConnection.status.in_(("connected", "needs_attention"))))


def _when(ts: str | None) -> datetime:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return utcnow()


def apply_status(msg: WhatsAppMessage, status: str, ts: str | None, errors: list[dict]) -> bool:
    """Move a message record forward. Returns whether anything changed (False for a repeat, an out-of-order older status or a failure after delivery)."""
    when = _when(ts)
    if status == "failed":
        if msg.delivery_status in ("delivered", "read", "failed"):
            return False
        msg.delivery_status, msg.error_code = "failed", (errors[0]["code"] if errors else None)
    elif status in RANK:
        if RANK[status] <= RANK.get(msg.delivery_status, -1):
            return False
        msg.delivery_status = status
        if status == "sent":
            msg.sent_at = msg.sent_at or when
        elif status == "delivered":
            msg.delivered_at = msg.delivered_at or when
        elif status == "read":
            msg.read_at = msg.read_at or when
    else:
        return False
    msg.status_updated_at = when
    return True


def process_event(db: Session, event_id: uuid.UUID) -> dict:
    """Process one stored delivery (idempotent). The caller supplies a session in the bypass context; every query below names its tenant explicitly from the verified mapping."""
    ev = db.scalar(select(WhatsAppWebhookEvent).where(WhatsAppWebhookEvent.id == event_id).with_for_update(skip_locked=True))
    if ev is None:
        return {"skipped": "missing_or_locked"}
    if ev.status in ("processed", "ignored"):
        return {"skipped": "already_done"}
    ev.attempts += 1
    out = {"statuses": 0, "opt_outs": 0, "attention": 0, "ignored_items": 0}
    tenants: set[uuid.UUID] = set()
    for item in (ev.payload or {}).get("items", []):
        conn = _connection_for(db, item.get("phone_number_id"))
        if conn is None:  # unknown, disconnected or still-pending number: never attributed to anyone
            out["ignored_items"] += 1
            continue
        tenants.add(conn.tenant_id)
        tenant = db.get(Tenant, conn.tenant_id)
        for s in item.get("statuses", []):
            msg = db.scalar(select(WhatsAppMessage).where(WhatsAppMessage.tenant_id == conn.tenant_id, WhatsAppMessage.phone_number_id == conn.phone_number_id, WhatsAppMessage.meta_message_id == s["id"]))
            if msg is not None and apply_status(msg, s["status"], s.get("timestamp"), s.get("errors", [])):
                out["statuses"] += 1
        for m in item.get("messages", []):
            if m.get("from") and rules.is_opt_out(m.get("text")) and tenant is not None:
                if consent.opt_out_by_phone(db, tenant, "+" + m["from"]):
                    out["opt_outs"] += 1
            elif m.get("from") and tenant is not None:  # not a STOP: is it a customer opting in (the QR page's message, or an opt-in keyword)?
                from app.services.whatsapp import optin
                joined = optin.handle_inbound(db, tenant, "+" + m["from"], m.get("text"), m.get("id") or "")
                if joined:
                    out["opt_ins"] = out.get("opt_ins", 0) + 1
                elif consent.note_reply(db, tenant, "+" + m["from"], _when(m.get("timestamp"))):  # an ordinary message from a known customer: remember WHEN, never what
                    out["replies"] = out.get("replies", 0) + 1
        if item.get("field") == "account_update" and item.get("event") in ATTENTION_EVENTS:
            conn.status, conn.attention_reason = "needs_attention", "Meta reported a problem with your WhatsApp account. Open WhatsApp Manager to see why."
            out["attention"] += 1
    ev.tenant_id = next(iter(tenants)) if len(tenants) == 1 else None  # a body that spans several businesses stays unattributed; each item was handled under its own tenant
    ev.status = "processed" if tenants else "ignored"
    ev.processed_at, ev.error = utcnow(), None
    ev.payload = {"items": [{**it, "messages": [{**mm, "text": None} for mm in it.get("messages", [])]} for it in (ev.payload or {}).get("items", [])]}  # the text was only needed to recognise STOP and opt-ins: once handled it is gone
    return out


def purge_old(db: Session, now: datetime | None = None) -> int:
    from datetime import timedelta
    from sqlalchemy import delete
    cutoff = (now or utcnow()) - timedelta(days=settings.whatsapp_event_retention_days)
    return db.execute(delete(WhatsAppWebhookEvent).where(WhatsAppWebhookEvent.received_at < cutoff, WhatsAppWebhookEvent.status.in_(("processed", "ignored", "failed")))).rowcount or 0


def stale_event_ids(db: Session, minutes: int = 2, limit: int = 200) -> list[uuid.UUID]:
    from datetime import timedelta
    cutoff = utcnow() - timedelta(minutes=minutes)
    return list(db.scalars(select(WhatsAppWebhookEvent.id).where(WhatsAppWebhookEvent.status == "received", WhatsAppWebhookEvent.received_at < cutoff, WhatsAppWebhookEvent.attempts < 5).limit(limit)))
