"""A business's connection to its own WhatsApp number through Meta Embedded Signup.

Flow: (1) `start_signup` mints a one-time `state` and returns what the browser needs to open Meta's popup (the PUBLIC app id and configuration id; never a secret). (2) The popup returns a one-time
`code` and the ids of the chosen account and number. (3) `complete_signup` checks the state (single use, 15 minutes, this business and this user), exchanges the code for a business token ON THE SERVER,
verifies with Meta that the token really was granted that account and number (the ids from the browser are untrusted), stores the token encrypted, subscribes FlowQR's app to the account's webhooks
and records the tenant -> account -> phone_number_id mapping that is the ONLY way a webhook or a send is ever attributed to a business.

The token is never returned, logged, exported or put in an audit entry. Nothing here sends a WhatsApp message.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import ensure_verified
from app.core.security import get_cipher, hash_token, new_token
from app.models import Tenant, User
from app.models.base import utcnow
from app.models.whatsapp import WhatsAppConnection
from app.services.audit import audit
from app.services.whatsapp import WaError
from app.services.whatsapp import addons
from app.services.whatsapp.meta import MetaError, get_meta_client

log = logging.getLogger("flowqr.whatsapp.connection")
TOKEN_WARN_DAYS = 7


def require_enabled() -> None:
    if not settings.whatsapp_enabled:
        raise WaError(404, "whatsapp_disabled", "WhatsApp automation is not switched on.")


def signup_configured() -> bool:
    return bool(settings.whatsapp_signup_enabled and settings.meta_app_id and settings.meta_app_secret and settings.whatsapp_embedded_signup_config_id and settings.token_encryption_key)


def live_connection(db: Session, tenant_id: uuid.UUID) -> WhatsAppConnection | None:
    return db.scalar(select(WhatsAppConnection).where(WhatsAppConnection.tenant_id == tenant_id, WhatsAppConnection.status != "disconnected"))


def connected_connection(db: Session, tenant_id: uuid.UUID) -> WhatsAppConnection | None:
    return db.scalar(select(WhatsAppConnection).where(WhatsAppConnection.tenant_id == tenant_id, WhatsAppConnection.status.in_(("connected", "needs_attention")), WhatsAppConnection.phone_number_id.is_not(None)))


def token_state(c: WhatsAppConnection, now: datetime | None = None) -> str:
    now = now or utcnow()
    if not c.access_token_enc:
        return "missing"
    if c.token_expires_at is None:
        return "no_expiry"
    if c.token_expires_at <= now:
        return "expired"
    return "expiring" if c.token_expires_at - now <= timedelta(days=TOKEN_WARN_DAYS) else "ok"


def serialize(c: WhatsAppConnection | None) -> dict | None:
    """What the screen may see. Deliberately has no token, no state and no raw Meta ids beyond the shown number."""
    if c is None:
        return None
    return {"id": c.id, "status": c.status, "display_phone_number": c.display_phone_number, "verified_name": c.verified_name, "quality_rating": c.quality_rating,
            "is_test_number": c.is_test_number, "webhook_status": c.webhook_status, "attention_reason": c.attention_reason, "connected_at": c.connected_at,
            "token_state": token_state(c)}


def start_signup(db: Session, tenant: Tenant, user: User, ip: str | None = None) -> dict:
    require_enabled()
    if not signup_configured():
        raise WaError(503, "not_configured", "Connecting WhatsApp is not available yet. FlowQR is still completing its set-up with Meta.")
    ensure_verified(user)
    if settings.whatsapp_require_addon and addons.active_addon(db, tenant.id) is None:
        raise WaError(402, "addon_required", "WhatsApp automation is an add-on. Ask FlowQR to switch it on for your business.")
    live = live_connection(db, tenant.id)
    if live is not None and live.status != "pending":
        raise WaError(409, "already_connected", "A WhatsApp number is already connected. Disconnect it first to connect a different one.")
    state = new_token()
    expires = utcnow() + timedelta(minutes=settings.whatsapp_connect_state_minutes)
    if live is None:
        live = WhatsAppConnection(tenant_id=tenant.id, status="pending", started_by=user.id)
        db.add(live)
    live.state_hash, live.state_expires_at, live.started_by = hash_token(state), expires, user.id
    db.flush()
    audit(db, action="whatsapp.connect_start", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_connection", entity_id=live.id, ip=ip)
    return {"app_id": settings.meta_app_id, "config_id": settings.whatsapp_embedded_signup_config_id, "graph_version": settings.whatsapp_graph_version, "state": state, "expires_at": expires}


def _expiry(debug: dict) -> datetime | None:
    exp = debug.get("expires_at")
    if isinstance(exp, (int, float)) and exp > 0:
        return datetime.fromtimestamp(exp, tz=timezone.utc)
    return None  # 0 or absent: Meta reports no expiry (business integration tokens)


def _granted_wabas(debug: dict) -> set[str]:
    ids: set[str] = set()
    for g in debug.get("granular_scopes") or []:
        if isinstance(g, dict) and str(g.get("scope", "")).startswith("whatsapp_business"):
            ids.update(str(t) for t in g.get("target_ids") or [])
    return ids


def complete_signup(db: Session, tenant: Tenant, user: User, *, state: str, code: str, waba_id: str, phone_number_id: str, ip: str | None = None) -> WhatsAppConnection:
    require_enabled()
    if not signup_configured():
        raise WaError(503, "not_configured", "Connecting WhatsApp is not available yet.")
    pending = db.scalar(select(WhatsAppConnection).where(WhatsAppConnection.tenant_id == tenant.id, WhatsAppConnection.status == "pending", WhatsAppConnection.state_hash == hash_token(state or "")))
    if pending is None or pending.started_by != user.id or pending.state_expires_at is None or pending.state_expires_at <= utcnow():
        raise WaError(400, "invalid_state", "This connection attempt expired or does not belong to you. Press Connect WhatsApp to start again.")
    pending.state_hash = None  # single use: even a failed attempt cannot be replayed
    db.flush()
    meta = get_meta_client()
    try:
        token = meta.exchange_code(code)
        debug = meta.debug_token(token)
        if not debug.get("is_valid", False):
            raise WaError(400, "token_invalid", "Meta did not accept the connection. Please try again.")
        if waba_id not in _granted_wabas(debug):  # the ids came from the browser: trust only what Meta says this token was granted
            raise WaError(400, "account_mismatch", "That WhatsApp account was not shared with FlowQR. Please try again and keep the account selected.")
        phone = meta.phone_number(token, phone_number_id)
        webhook_ok = True
        try:
            meta.subscribe_app(token, waba_id)
        except MetaError:
            webhook_ok = False
    except MetaError as exc:
        log.warning("WhatsApp signup failed: %s", exc.message)
        raise WaError(502 if exc.retryable else 400, "meta_error", "Meta could not complete the connection. Please try again in a few minutes.") from None
    pending.waba_id, pending.phone_number_id = waba_id, phone_number_id
    pending.display_phone_number = (phone.get("display_phone_number") or "")[:32] or None
    pending.verified_name = (phone.get("verified_name") or "")[:160] or None
    pending.quality_rating = (phone.get("quality_rating") or "")[:16] or None
    pending.is_test_number = "".join(ch for ch in (pending.display_phone_number or "") if ch.isdigit()).startswith("1555")
    pending.access_token_enc = get_cipher().encrypt(token)
    pending.token_expires_at, pending.token_checked_at = _expiry(debug), utcnow()
    pending.webhook_status = "subscribed" if webhook_ok else "failed"
    pending.status = "connected" if webhook_ok else "needs_attention"
    pending.attention_reason = None if webhook_ok else "We could not turn on delivery updates. Press Check connection to try again."
    pending.connected_at, pending.state_expires_at = utcnow(), None
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise WaError(409, "number_in_use", "That WhatsApp number is already connected to another business on FlowQR.") from None
    audit(db, action="whatsapp.connect", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_connection", entity_id=pending.id,
          meta={"phone": pending.display_phone_number, "test_number": pending.is_test_number, "webhook": pending.webhook_status}, ip=ip)
    return pending


def _token_of(c: WhatsAppConnection) -> str | None:
    if not c.access_token_enc:
        return None
    try:
        return get_cipher().decrypt(c.access_token_enc)
    except RuntimeError:
        return None


def refresh(db: Session, c: WhatsAppConnection, *, user_id: uuid.UUID | None = None, ip: str | None = None) -> WhatsAppConnection:
    """Ask Meta whether the connection still works (token valid, number reachable, webhook subscribed) and record the answer in plain words."""
    token = _token_of(c)
    now = utcnow()
    if token is None:
        c.status, c.attention_reason = "needs_attention", "The connection needs to be set up again. Press Connect WhatsApp."
        return c
    meta = get_meta_client()
    try:
        debug = meta.debug_token(token)
        if not debug.get("is_valid", False):
            c.status, c.attention_reason = "needs_attention", "Meta no longer accepts this connection. Press Connect WhatsApp to connect again."
            c.token_checked_at = now
            return c
        c.token_expires_at = _expiry(debug)
        phone = meta.phone_number(token, c.phone_number_id)
        c.display_phone_number = (phone.get("display_phone_number") or c.display_phone_number or "")[:32] or None
        c.verified_name = (phone.get("verified_name") or c.verified_name or "")[:160] or None
        c.quality_rating = (phone.get("quality_rating") or "")[:16] or None
        try:
            meta.subscribe_app(token, c.waba_id)
            c.webhook_status = "subscribed"
        except MetaError:
            c.webhook_status = "failed"
    except MetaError as exc:
        if exc.retryable:
            raise WaError(502, "meta_unreachable", "Could not reach Meta just now. Please try again in a few minutes.") from None
        c.status, c.attention_reason = "needs_attention", "Meta no longer accepts this connection. Press Connect WhatsApp to connect again."
        c.token_checked_at = now
        return c
    c.token_checked_at = now
    state = token_state(c, now)
    if state == "expired":
        c.status, c.attention_reason = "needs_attention", "Your WhatsApp connection has expired. Press Connect WhatsApp to renew it."
    elif c.webhook_status == "failed":
        c.status, c.attention_reason = "needs_attention", "We could not turn on delivery updates. Press Check connection to try again."
    else:
        c.status = "connected"
        c.attention_reason = "Your WhatsApp connection expires soon. Press Connect WhatsApp to renew it." if state == "expiring" else None
    if user_id:
        audit(db, action="whatsapp.connection_check", tenant_id=c.tenant_id, user_id=user_id, entity_type="whatsapp_connection", entity_id=c.id, meta={"status": c.status}, ip=ip)
    return c


def _unsubscribe(c: WhatsAppConnection) -> bool:
    token = _token_of(c)
    if not token or not c.waba_id:
        return True
    try:
        get_meta_client().unsubscribe_app(token, c.waba_id)
        return True
    except MetaError:
        return False


def disconnect(db: Session, tenant: Tenant, user: User, ip: str | None = None) -> WhatsAppConnection:
    c = live_connection(db, tenant.id)
    if c is None:
        raise WaError(404, "not_connected", "No WhatsApp number is connected.")
    unsubscribed = _unsubscribe(c)  # best effort: a failure here must never keep a business connected against its wishes
    c.status, c.access_token_enc, c.token_expires_at = "disconnected", None, None
    c.state_hash, c.state_expires_at, c.webhook_status, c.attention_reason = None, None, "unknown", None
    c.disconnected_at = utcnow()
    db.flush()
    audit(db, action="whatsapp.disconnect", tenant_id=tenant.id, user_id=user.id, entity_type="whatsapp_connection", entity_id=c.id, meta={"unsubscribed": unsubscribed}, ip=ip)
    return c


def on_tenant_delete(db: Session, tenant_id: uuid.UUID) -> None:
    """Before a business is deleted: stop Meta sending its events to FlowQR. Best effort and never raises (the rows and the encrypted token go with the business)."""
    try:
        for c in db.scalars(select(WhatsAppConnection).where(WhatsAppConnection.tenant_id == tenant_id, WhatsAppConnection.status != "disconnected")):
            _unsubscribe(c)
    except Exception:  # noqa: BLE001
        log.warning("WhatsApp unsubscribe on business deletion failed")


def check_all(db: Session) -> dict:
    """Housekeeping: connections not checked for a day are re-checked, so an expiring or revoked token is noticed before a send would fail."""
    due = utcnow() - timedelta(hours=20)
    checked = problems = 0
    for c in db.scalars(select(WhatsAppConnection).where(WhatsAppConnection.status.in_(("connected", "needs_attention")), (WhatsAppConnection.token_checked_at.is_(None)) | (WhatsAppConnection.token_checked_at < due))):
        try:
            refresh(db, c)
            checked += 1
            problems += int(c.status == "needs_attention")
        except WaError:
            pass
    return {"checked": checked, "needs_attention": problems}
