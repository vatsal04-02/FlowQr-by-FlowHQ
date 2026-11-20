"""Integrations (Phase 10): per-business API keys, an idempotent inbound API, and signed outbound webhooks. Ships OFF (WHATSAPP_INTEGRATIONS_ENABLED) and is part of the Pro tier only.

KEYS. A key is shown once. Only its SHA-256 hash is stored (a key is 32 random bytes, so a plain hash is enough and lets us look it up directly). A key belongs to one business, has scopes, can expire and
be revoked (it stops working at once), and is rate-limited. Using a key on a business that is not on Pro, or while the platform switch is off, is refused.

INBOUND. Every POST needs an `Idempotency-Key`; a retry with the same key returns the first answer and does nothing twice, and the same key with a different body is refused. **Nothing the API does can
create consent by itself**: a customer is created or updated with NO consent unless the request carries `consent` with `agreed: true` and a written note of how they agreed (at least 10 characters),
which is the same attested rule as an owner typing a customer in (source `api_integration`). Someone who replied STOP cannot be added back this way.

OUTBOUND. Events (`message.status`, `contact.opted_out`, `conversation.created`, `booking.created`, `booking.updated`) are written as delivery rows in the same transaction as the thing that happened, then
sent by a worker: HTTPS only, to public addresses only (checked immediately before every send; no redirects are followed), signed with HMAC-SHA256 (`X-FlowQR-Signature: t=<unix>,v1=<hex>` over "t.body"), retried
with backoff and then marked dead. No event ever carries message text. The envelope is the same for every event type, so connectors (for example Shopify or Razorpay) can be added later: none is built."""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import re
import secrets
import socket
import uuid
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.rate_limit import hit
from app.core.security import get_cipher
from app.models import Tenant, User
from app.models.base import utcnow
from app.models.whatsapp import (API_SCOPES, WEBHOOK_EVENTS, WhatsAppApiKey, WhatsAppApiRequest, WhatsAppBooking, WhatsAppContact, WhatsAppWebhookDelivery, WhatsAppWebhookEndpoint)
from app.services.audit import audit
from app.services.whatsapp import WaError, addons, automations, bookings, consent

log = logging.getLogger("flowqr.whatsapp.integrations")
API_VERSION = "2026-11-20"
KEY_PREFIX = "fqk_"
MAX_KEYS = 10
MAX_ENDPOINTS = 5
MAX_PAYLOAD_BYTES = 16_000
BACKOFF = [60, 300, 1800, 7200, 21600]  # seconds after the 1st, 2nd... failed attempt; the 6th failure marks the delivery dead
MAX_ATTEMPTS = len(BACKOFF) + 1
ENDPOINT_DISABLE_AFTER = 10  # dead deliveries in a row
IDEM_RE = re.compile(r"^[A-Za-z0-9_.:\-]{8,64}$")
SCOPE_WORDS = {"customers:write": "Add or update customers", "visits:write": "Record a visit", "enquiries:write": "Add an enquiry", "bookings:write": "Create a booking"}
EVENT_WORDS = {"message.status": "A message was sent, delivered, read or failed", "contact.opted_out": "A customer replied STOP", "conversation.created": "A customer wrote for the first time",
               "booking.created": "A booking was made", "booking.updated": "A booking was moved, cancelled, or marked done or no-show"}


# ---- switches
def platform_on() -> bool:
    return bool(settings.whatsapp_enabled and settings.whatsapp_integrations_enabled and settings.token_encryption_key)


def enabled_for(db: Session, tenant_id: uuid.UUID) -> bool:
    return platform_on() and addons.integrations_allowed(db, tenant_id)


# ---- keys
def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def _clean_scopes(scopes) -> list[str]:
    out = []
    for s in scopes or []:
        if s not in API_SCOPES:
            raise WaError(422, "invalid_scope", f"Unknown scope: {s}.")
        if s not in out:
            out.append(s)
    if not out:
        raise WaError(422, "scope_required", "Choose at least one thing this key may do.")
    return out


def serialize_key(k: WhatsAppApiKey) -> dict:
    return {"id": k.id, "name": k.name, "prefix": k.prefix, "scopes": list(k.scopes or []), "rate_limit_per_min": k.rate_limit_per_min, "created_at": k.created_at, "last_used_at": k.last_used_at,
            "expires_at": k.expires_at, "revoked_at": k.revoked_at, "active": k.revoked_at is None and (k.expires_at is None or k.expires_at > utcnow())}


def create_key(db: Session, tenant: Tenant, user: User, *, name: str, scopes, rate_limit_per_min: int = 60, expires_in_days: int | None = None, ip: str | None = None) -> tuple[WhatsAppApiKey, str]:
    """Returns (row, the key). The key cannot be read again."""
    name = " ".join((name or "").split())[:80]
    if len(name) < 2:
        raise WaError(422, "name_required", "Give the key a name, for example the system that will use it.")
    if isinstance(rate_limit_per_min, bool) or not isinstance(rate_limit_per_min, int) or not 10 <= rate_limit_per_min <= 600:
        raise WaError(422, "invalid_rate", "The limit must be from 10 to 600 requests a minute.")
    if expires_in_days is not None and (isinstance(expires_in_days, bool) or not isinstance(expires_in_days, int) or not 1 <= expires_in_days <= 730):
        raise WaError(422, "invalid_expiry", "A key can last from 1 to 730 days.")
    live = db.scalars(select(WhatsAppApiKey).where(WhatsAppApiKey.tenant_id == tenant.id, WhatsAppApiKey.revoked_at.is_(None))).all()
    if len(live) >= MAX_KEYS:
        raise WaError(409, "too_many", f"You can have up to {MAX_KEYS} active keys. Revoke one first.")
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    row = WhatsAppApiKey(tenant_id=tenant.id, name=name, prefix=key[:12], key_hash=_hash(key), scopes=_clean_scopes(scopes), rate_limit_per_min=rate_limit_per_min, created_by=user.id,
                         expires_at=(utcnow() + timedelta(days=expires_in_days)) if expires_in_days else None)
    db.add(row)
    db.flush()
    audit(db, action="whatsapp.api_key_create", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_api_key", entity_id=row.id, meta={"name": name, "scopes": row.scopes}, ip=ip)
    return row, key


def revoke_key(db: Session, tenant: Tenant, user: User, key_id: uuid.UUID, ip: str | None = None) -> WhatsAppApiKey:
    k = db.get(WhatsAppApiKey, key_id)
    if k is None or k.tenant_id != tenant.id:
        raise WaError(404, "not_found", "That key was not found.")
    if k.revoked_at is None:
        k.revoked_at = utcnow()
        audit(db, action="whatsapp.api_key_revoke", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_api_key", entity_id=k.id, ip=ip)
    return k


def authenticate(db: Session, token: str | None, now: datetime | None = None) -> WhatsAppApiKey | None:
    """The key row for a presented key, or None. Never says why, and never reveals whether a prefix exists. Call under bypass: the tenant is not known until the key is."""
    now = now or utcnow()
    if not token or not token.startswith(KEY_PREFIX) or len(token) > 120:
        return None
    k = db.scalar(select(WhatsAppApiKey).where(WhatsAppApiKey.key_hash == _hash(token)))
    if k is None or not hmac.compare_digest(k.key_hash, _hash(token)) or k.revoked_at is not None or (k.expires_at is not None and k.expires_at <= now):
        return None
    if k.last_used_at is None or now - k.last_used_at > timedelta(minutes=1):
        k.last_used_at = now
    return k


def check_rate(key: WhatsAppApiKey) -> bool:
    return hit(f"wa-api:{key.id}", key.rate_limit_per_min, 60)


# ---- idempotency
def canonical_hash(path: str, body: dict) -> str:
    return hashlib.sha256((path + "\n" + json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)).encode()).hexdigest()


def idempotent(db: Session, key: WhatsAppApiKey, idem: str | None, path: str, body: dict, handler) -> tuple[int, dict, bool]:
    """(status, response, replay). Runs `handler()` at most once per (key, Idempotency-Key). A repeat returns the first answer; the same Idempotency-Key with a different request is refused."""
    if not idem or not IDEM_RE.match(idem):
        raise WaError(422, "idempotency_key_required", "Send an Idempotency-Key header of 8 to 64 letters, digits, dashes or underscores. Use a new one for each different request.")
    h = canonical_hash(path, body)
    old = db.scalar(select(WhatsAppApiRequest).where(WhatsAppApiRequest.tenant_id == key.tenant_id, WhatsAppApiRequest.key_id == key.id, WhatsAppApiRequest.idem_key == idem))
    if old is not None:
        if old.request_hash != h:
            raise WaError(422, "idempotency_conflict", "That Idempotency-Key was already used for a different request.")
        return old.status_code, old.response, True
    status, response = handler()
    response = json.loads(json.dumps(response, default=str))  # exactly what is stored and what a replay returns: the first answer and every later one are identical
    db.add(WhatsAppApiRequest(tenant_id=key.tenant_id, key_id=key.id, idem_key=idem, request_hash=h, status_code=status, response=response))
    db.flush()
    return status, response, False


# ---- inbound operations
def _consent_block(db: Session, tenant: Tenant, contact: WhatsAppContact, block: dict | None, ip: str | None) -> dict:
    """Records consent only when the request says the customer agreed AND says how. Anything less records nothing. Returns what was recorded."""
    if not block:
        return {}
    if block.get("agreed") is not True:
        raise WaError(422, "agreement_required", "To record consent, send consent.agreed true. Leave consent out to record none.")
    purposes = block.get("purposes") or []
    if not purposes or any(p not in ("utility", "marketing", "occasion") for p in purposes):
        raise WaError(422, "invalid_purpose", "consent.purposes must list utility, marketing or occasion.")
    note = " ".join(str(block.get("evidence") or "").split())
    if len(note) < 10:
        raise WaError(422, "evidence_required", "Write in consent.evidence how the customer agreed (at least 10 characters), for example: ticked the WhatsApp box at checkout on 12 Nov.")
    out = {}
    for p in dict.fromkeys(purposes):
        row, created = consent.grant(db, tenant, contact, p, "api_integration", attested=True, evidence=note, ip=ip)
        out[p] = "recorded" if created else "already_recorded"
    return out


def serialize_customer(db: Session, c: WhatsAppContact) -> dict:
    cm = consent.consent_map(db, [c.id]).get(c.id, {})
    return {"id": c.id, "phone": c.phone, "name": c.customer_name, "opted_out": c.marketing_opted_out_at is not None, "consent": {k: bool(cm.get(k)) for k in ("utility", "marketing", "occasion")}}


def upsert_customer(db: Session, tenant: Tenant, body: dict, ip: str | None = None) -> dict:
    c, created = consent.create_contact(db, tenant, phone=body.get("phone") or "", name=body.get("name"), tags=body.get("tags") or [], source="api_integration", user_id=None)
    recorded = _consent_block(db, tenant, c, body.get("consent"), ip)
    audit(db, action="whatsapp.api_customer", tenant_id=tenant.id, entity_type="whatsapp_contact", entity_id=c.id, meta={"created": created, "consent": list(recorded)}, ip=ip)
    return {**serialize_customer(db, c), "created": created, "consent_recorded": recorded}


def record_visit(db: Session, tenant: Tenant, body: dict, now: datetime | None = None) -> dict:
    now = now or utcnow()
    c = consent.find_by_phone(db, tenant.id, consent.e164(body.get("phone") or ""))
    if c is None:
        raise WaError(404, "customer_not_found", "No customer with that phone number. Add the customer first.")
    when = now
    if body.get("visited_at"):
        try:
            when = datetime.fromisoformat(str(body["visited_at"]).replace("Z", "+00:00"))
        except ValueError:
            raise WaError(422, "invalid_time", "visited_at must be an ISO 8601 time.")
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        if when > now + timedelta(minutes=5) or when < now - timedelta(days=60):
            raise WaError(422, "invalid_time", "visited_at must be within the last 60 days and not in the future.")
    consent.mark_visit(db, c, when)
    try:
        review = automations.on_visit_completed(db, tenant, c, None, now)
    except WaError:
        review = {"scheduled": False, "reason": "automation_off"}
    return {"customer_id": c.id, "visit_recorded": True, "review_request": {"scheduled": bool(review.get("scheduled")), "reason": review.get("reason")}}


def add_enquiry(db: Session, tenant: Tenant, body: dict, ip: str | None = None, now: datetime | None = None) -> dict:
    c, created = consent.create_contact(db, tenant, phone=body.get("phone") or "", name=body.get("name"), tags=["enquiry"], source="api_integration", user_id=None)
    c.last_enquiry_at = now or utcnow()
    recorded = _consent_block(db, tenant, c, body.get("consent"), ip)
    return {**serialize_customer(db, c), "created": created, "enquiry_recorded": True, "consent_recorded": recorded}


def create_booking(db: Session, tenant: Tenant, key: WhatsAppApiKey, idem: str, body: dict, ip: str | None = None) -> dict:
    if not bookings.enabled_for(db, tenant.id):
        raise WaError(409, "not_bookable", bookings.BOOKING_WORDS["not_bookable"])
    ref = (body.get("service") or "").strip()
    svc = None
    for s in bookings.services(db, tenant.id, active_only=True):
        if str(s.id) == ref or s.name.lower() == ref.lower():
            svc = s
    if svc is None:
        raise WaError(404, "service_not_found", bookings.BOOKING_WORDS["service_not_found"])
    c, _ = consent.create_contact(db, tenant, phone=body.get("phone") or "", name=body.get("name"), tags=[], source="api_integration", user_id=None)
    b, created = bookings.book(db, tenant, c, svc, bookings.parse_start(body.get("date") or "", body.get("time") or ""), source="api", idem_key=f"api:{key.id}:{idem}", note=body.get("note"), ip=ip)
    return {**bookings.serialize(b, c), "created": created}


# ---- outbound: endpoints
_resolve = socket.getaddrinfo  # a seam: tests replace it so no real DNS is used
def _real_post(url: str, content: bytes, headers: dict, timeout: float, follow_redirects: bool, extensions: dict):
    """One request, no proxies from the environment, no redirects. `extensions` carries the real host name for TLS (SNI and certificate check) while the connection goes to the address we just validated."""
    with httpx.Client(timeout=timeout, follow_redirects=follow_redirects, trust_env=False) as c:
        return c.post(url, content=content, headers=headers, extensions=extensions)


_post = _real_post  # a seam: tests replace it so nothing is really sent
BAD_HOSTS = ("localhost", ".local", ".internal", ".localdomain", ".lan", ".home")


def target(url: str) -> tuple[str, str, str]:
    """Validate an endpoint address and return (url, host, the first validated IP). HTTPS only, no credentials, a normal port, and EVERY address the name resolves to must be a public one (no loopback,
    private, link-local or metadata addresses). Raises WaError."""
    u = (url or "").strip()
    if len(u) > 500:
        raise WaError(422, "invalid_url", "That address is too long.")
    try:
        p = urlparse(u)
        port = p.port
    except ValueError:
        raise WaError(422, "invalid_url", "That address is not valid.")
    if p.scheme != "https" or not p.hostname:
        raise WaError(422, "invalid_url", "Use an https:// address.")
    if p.username or p.password:
        raise WaError(422, "invalid_url", "The address cannot contain a user name or password.")
    if port not in (None, 443, 8443):
        raise WaError(422, "invalid_url", "Use port 443 (the default) or 8443.")
    host = p.hostname.lower().rstrip(".")
    if host == "localhost" or any(host.endswith(s) for s in BAD_HOSTS if s.startswith(".")):
        raise WaError(422, "address_not_allowed", "That address is not reachable from the internet.")
    try:
        infos = _resolve(host, port or 443, type=socket.SOCK_STREAM)
    except OSError:
        raise WaError(422, "address_not_found", "That address could not be found.")
    addrs = {i[4][0] for i in infos}
    if not addrs:
        raise WaError(422, "address_not_found", "That address could not be found.")
    for a in addrs:
        ip = ipaddress.ip_address(a.split("%")[0])
        if ip.version == 6 and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise WaError(422, "address_not_allowed", "That address is not reachable from the internet.")
    return u, host, sorted(addrs)[0].split("%")[0]


def check_url(url: str) -> str:
    return target(url)[0]


def _events(events) -> list[str]:
    out = [e for e in dict.fromkeys(events or [])]
    if not out or any(e not in WEBHOOK_EVENTS for e in out):
        raise WaError(422, "invalid_events", "Choose at least one of: " + ", ".join(WEBHOOK_EVENTS) + ".")
    return out


def serialize_endpoint(e: WhatsAppWebhookEndpoint) -> dict:
    return {"id": e.id, "url": e.url, "events": list(e.events or []), "active": e.active, "disabled_reason": e.disabled_reason, "secret_hint": e.secret_hint, "failure_streak": e.failure_streak,
            "last_success_at": e.last_success_at, "last_failure_at": e.last_failure_at, "created_at": e.created_at}


def _new_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def create_endpoint(db: Session, tenant: Tenant, user: User, *, url: str, events, ip: str | None = None) -> tuple[WhatsAppWebhookEndpoint, str]:
    """Returns (row, signing secret). The secret cannot be read again (it can be replaced)."""
    if len(db.scalars(select(WhatsAppWebhookEndpoint).where(WhatsAppWebhookEndpoint.tenant_id == tenant.id)).all()) >= MAX_ENDPOINTS:
        raise WaError(409, "too_many", f"You can have up to {MAX_ENDPOINTS} endpoints.")
    url, ev, secret = check_url(url), _events(events), _new_secret()
    row = WhatsAppWebhookEndpoint(tenant_id=tenant.id, url=url, secret_enc=get_cipher().encrypt(secret), secret_hint=secret[-4:], events=ev, active=True, created_by=user.id)
    db.add(row)
    db.flush()
    audit(db, action="whatsapp.webhook_endpoint_create", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_webhook_endpoint", entity_id=row.id, meta={"events": ev}, ip=ip)
    return row, secret


def get_endpoint(db: Session, tenant_id: uuid.UUID, endpoint_id: uuid.UUID) -> WhatsAppWebhookEndpoint:
    e = db.get(WhatsAppWebhookEndpoint, endpoint_id)
    if e is None or e.tenant_id != tenant_id:
        raise WaError(404, "not_found", "That endpoint was not found.")
    return e


def update_endpoint(db: Session, tenant: Tenant, user: User, e: WhatsAppWebhookEndpoint, *, url=None, events=None, active=None, rotate_secret: bool = False, ip: str | None = None) -> tuple[WhatsAppWebhookEndpoint, str | None]:
    secret = None
    if url is not None and url != e.url:
        e.url = check_url(url)
    if events is not None:
        e.events = _events(events)
    if active is not None:
        e.active = bool(active)
        if e.active:
            e.disabled_reason, e.failure_streak = None, 0
    if rotate_secret:
        secret = _new_secret()
        e.secret_enc, e.secret_hint = get_cipher().encrypt(secret), secret[-4:]
    db.flush()
    audit(db, action="whatsapp.webhook_endpoint_update", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_webhook_endpoint", entity_id=e.id, meta={"rotated": rotate_secret, "active": e.active}, ip=ip)
    return e, secret


def delete_endpoint(db: Session, tenant: Tenant, user: User, e: WhatsAppWebhookEndpoint, ip: str | None = None) -> None:
    audit(db, action="whatsapp.webhook_endpoint_delete", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_webhook_endpoint", entity_id=e.id, ip=ip)
    db.delete(e)
    db.flush()


def serialize_delivery(d: WhatsAppWebhookDelivery) -> dict:
    return {"id": d.id, "endpoint_id": d.endpoint_id, "event_id": d.event_id, "event_type": d.event_type, "status": d.status, "attempts": d.attempts, "next_attempt_at": d.next_attempt_at,
            "last_status_code": d.last_status_code, "last_error": d.last_error, "created_at": d.created_at, "delivered_at": d.delivered_at}


def recent_deliveries(db: Session, tenant_id: uuid.UUID, limit: int = 50) -> list[dict]:
    return [serialize_delivery(d) for d in db.scalars(select(WhatsAppWebhookDelivery).where(WhatsAppWebhookDelivery.tenant_id == tenant_id).order_by(WhatsAppWebhookDelivery.created_at.desc()).limit(max(1, min(limit, 200))))]


# ---- outbound: events
def envelope(event_id: uuid.UUID, event_type: str, tenant_id: uuid.UUID, data: dict, now: datetime | None = None) -> dict:
    """The same shape for every event, so a connector can handle them all one way. `data` never holds message text."""
    return {"id": str(event_id), "type": event_type, "api_version": API_VERSION, "created_at": (now or utcnow()).isoformat(), "business_id": str(tenant_id), "data": json.loads(json.dumps(data, default=str))}


def emit(db: Session, tenant_id: uuid.UUID, event_type: str, data: dict, now: datetime | None = None) -> int:
    """Write one delivery per active endpoint that wants this event. Cheap when nobody is listening. Never raises into the caller: an event must never break what happened."""
    try:
        if not platform_on():
            return 0
        eps = db.scalars(select(WhatsAppWebhookEndpoint).where(WhatsAppWebhookEndpoint.tenant_id == tenant_id, WhatsAppWebhookEndpoint.active.is_(True))).all()
        eps = [e for e in eps if event_type in (e.events or [])]
        if not eps or not addons.integrations_allowed(db, tenant_id):
            return 0
        now = now or utcnow()
        eid = uuid.uuid4()
        payload = envelope(eid, event_type, tenant_id, data, now)
        if len(json.dumps(payload)) > MAX_PAYLOAD_BYTES:
            return 0
        with db.begin_nested():
            for e in eps:
                db.add(WhatsAppWebhookDelivery(tenant_id=tenant_id, endpoint_id=e.id, event_id=eid, event_type=event_type, payload=payload, status="pending", attempts=0, next_attempt_at=now))
        return len(eps)
    except Exception:  # noqa: BLE001
        log.exception("could not queue webhook event %s", event_type)
        return 0


def customer_ref(c: WhatsAppContact | None) -> dict:
    return {"customer_id": c.id, "customer_phone": c.phone} if c is not None else {}


def booking_event(db: Session, b: WhatsAppBooking, change: str, now: datetime | None = None) -> None:
    c = db.get(WhatsAppContact, b.contact_id)
    emit(db, b.tenant_id, "booking.created" if change == "created" else "booking.updated",
         {"change": change, "booking": {"id": b.id, "code": b.code, "status": b.status, "service": b.service_name, "starts_at": b.starts_at, "ends_at": b.ends_at, "source": b.source}, **customer_ref(c)}, now)


def sign(secret: str, timestamp: int, body: bytes) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


# ---- outbound: delivery
def _finish_fail(db: Session, d: WhatsAppWebhookDelivery, e: WhatsAppWebhookEndpoint | None, code: int | None, err: str, now: datetime) -> None:
    d.attempts += 1
    d.last_status_code, d.last_error = code, err[:120]
    if e is not None:
        e.last_failure_at = now
    if d.attempts >= MAX_ATTEMPTS:
        d.status, d.next_attempt_at = "dead", None
        if e is not None:
            e.failure_streak += 1
            if e.failure_streak >= ENDPOINT_DISABLE_AFTER and e.active:
                e.active, e.disabled_reason = False, "Switched off after too many failed deliveries in a row."
    else:
        d.next_attempt_at = now + timedelta(seconds=BACKOFF[d.attempts - 1])


def deliver(db: Session, d: WhatsAppWebhookDelivery, now: datetime | None = None) -> str:
    now = now or utcnow()
    e = db.get(WhatsAppWebhookEndpoint, d.endpoint_id)
    if e is None or not e.active:
        d.status, d.next_attempt_at, d.last_error = "dead", None, "endpoint switched off"
        return "dead"
    try:
        url, host, ip = target(e.url)  # again, right before sending: a name can change what it points to
    except WaError as exc:
        _finish_fail(db, d, e, None, f"blocked: {exc.code}", now)
        return d.status
    p = urlparse(url)  # the connection goes to the address just checked (so the name cannot be re-pointed between the check and the send); the real name is kept for TLS and the Host header
    pinned = urlunparse(p._replace(netloc=(f"[{ip}]" if ":" in ip else ip) + (f":{p.port}" if p.port else "")))
    body = json.dumps(d.payload, separators=(",", ":"), default=str).encode()
    try:
        secret = get_cipher().decrypt(e.secret_enc)
    except RuntimeError:
        _finish_fail(db, d, e, None, "signing secret unreadable", now)
        return d.status
    ts = int(now.timestamp())
    headers = {"Host": host + (f":{p.port}" if p.port else ""), "Content-Type": "application/json", "User-Agent": "FlowQR-Webhooks/1", "X-FlowQR-Event": d.event_type, "X-FlowQR-Delivery": str(d.id), "X-FlowQR-Signature": f"t={ts},v1={sign(secret, ts, body)}"}
    try:
        r = _post(pinned, content=body, headers=headers, timeout=8.0, follow_redirects=False, extensions={"sni_hostname": host})
    except Exception as exc:  # noqa: BLE001 - any network failure is just a failed attempt
        _finish_fail(db, d, e, None, f"network error: {type(exc).__name__}", now)
        return d.status
    if 200 <= r.status_code < 300:
        d.attempts += 1
        d.status, d.delivered_at, d.next_attempt_at, d.last_status_code, d.last_error = "delivered", now, None, r.status_code, None
        e.last_success_at, e.failure_streak = now, 0
        return "delivered"
    if r.status_code == 410:  # the receiver says it is gone: stop sending
        e.active, e.disabled_reason = False, "The receiver answered 410 Gone."
        d.attempts += 1
        d.status, d.next_attempt_at, d.last_status_code, d.last_error = "dead", None, 410, "receiver gone"
        return "dead"
    _finish_fail(db, d, e, r.status_code, f"receiver answered {r.status_code}", now)
    return d.status


def run_deliveries(db: Session, now: datetime | None = None, limit: int = 100, tenant_id: uuid.UUID | None = None) -> dict:
    """The worker pass: every pending delivery that is due. Rows are locked (SKIP LOCKED) so two workers never send the same one. One failing receiver never stops the rest."""
    now = now or utcnow()
    out = {"delivered": 0, "retry": 0, "dead": 0}
    if not platform_on():
        return {"held": True}
    q = select(WhatsAppWebhookDelivery).where(WhatsAppWebhookDelivery.status == "pending", WhatsAppWebhookDelivery.next_attempt_at <= now)
    if tenant_id is not None:
        q = q.where(WhatsAppWebhookDelivery.tenant_id == tenant_id)
    for d in db.scalars(q.order_by(WhatsAppWebhookDelivery.next_attempt_at).limit(limit).with_for_update(skip_locked=True)):
        try:
            with db.begin_nested():
                r = deliver(db, d, now)
        except Exception:  # noqa: BLE001
            log.exception("webhook delivery %s failed", d.id)
            continue
        out["delivered" if r == "delivered" else "dead" if r == "dead" else "retry"] += 1
    return out


def send_test(db: Session, tenant: Tenant, e: WhatsAppWebhookEndpoint, now: datetime | None = None) -> WhatsAppWebhookDelivery:
    """A "ping" to one endpoint, delivered through the same signed path (and the same address checks)."""
    now = now or utcnow()
    eid = uuid.uuid4()
    d = WhatsAppWebhookDelivery(tenant_id=tenant.id, endpoint_id=e.id, event_id=eid, event_type="ping", payload=envelope(eid, "ping", tenant.id, {"message": "This is a test from FlowQR."}, now), status="pending", attempts=0, next_attempt_at=now)
    db.add(d)
    db.flush()
    deliver(db, d, now)
    return d


def retry_delivery(db: Session, tenant_id: uuid.UUID, delivery_id: uuid.UUID, now: datetime | None = None) -> WhatsAppWebhookDelivery:
    d = db.get(WhatsAppWebhookDelivery, delivery_id)
    if d is None or d.tenant_id != tenant_id:
        raise WaError(404, "not_found", "That delivery was not found.")
    if d.status != "dead":
        raise WaError(409, "not_dead", "Only a delivery that gave up can be tried again.")
    d.status, d.attempts, d.next_attempt_at, d.last_error = "pending", 0, now or utcnow(), None
    return d


def purge(db: Session, now: datetime | None = None) -> dict:
    now = now or utcnow()
    a = db.execute(delete(WhatsAppApiRequest).where(WhatsAppApiRequest.created_at < now - timedelta(hours=48))).rowcount or 0
    b = db.execute(delete(WhatsAppWebhookDelivery).where(WhatsAppWebhookDelivery.created_at < now - timedelta(days=14), WhatsAppWebhookDelivery.status != "pending")).rowcount or 0
    return {"api_requests": a, "deliveries": b}


def overview(db: Session, tenant: Tenant) -> dict:
    keys = db.scalars(select(WhatsAppApiKey).where(WhatsAppApiKey.tenant_id == tenant.id).order_by(WhatsAppApiKey.created_at.desc())).all()
    eps = db.scalars(select(WhatsAppWebhookEndpoint).where(WhatsAppWebhookEndpoint.tenant_id == tenant.id).order_by(WhatsAppWebhookEndpoint.created_at)).all()
    return {"platform_on": platform_on(), "plan_ok": addons.integrations_allowed(db, tenant.id), "keys": [serialize_key(k) for k in keys], "endpoints": [serialize_endpoint(e) for e in eps], "scopes": SCOPE_WORDS,
            "events": EVENT_WORDS, "api_version": API_VERSION, "base_path": "/api/v1/integrations/v1", "limits": {"keys": MAX_KEYS, "endpoints": MAX_ENDPOINTS}}
