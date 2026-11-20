"""The one question every send must pass (Phase 2 will call it; Phase 1 only proves it). `preflight` answers (ok, reason) with a stable code and NEVER sends anything.

Order of checks (the first failure wins): platform kill switches, the business's add-on, a healthy connection from THIS business, then consent for the purpose. A marketing message needs a live
marketing consent and no opt-out; a utility message needs utility consent. Template approval, category match, limits and duplicate suppression are added here in Phase 2."""
import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.whatsapp import WhatsAppContact
from app.services.whatsapp import addons, connection, consent


def preflight(db: Session, tenant_id: uuid.UUID, contact: WhatsAppContact, purpose: str, *, template=None, kind: str | None = None) -> tuple[bool, str]:
    if not settings.whatsapp_enabled:
        return False, "whatsapp_disabled"
    if settings.whatsapp_emergency_stop:
        return False, "emergency_stop"
    if not settings.whatsapp_sending_enabled:
        return False, "sending_disabled"  # Phase 1: nothing may send
    if settings.whatsapp_require_addon and addons.active_addon(db, tenant_id) is None:
        return False, "no_addon"
    conn = connection.connected_connection(db, tenant_id)
    if conn is None or conn.status != "connected":
        return False, "not_connected"
    if connection.token_state(conn) in ("missing", "expired"):
        return False, "token_expired"
    if kind == "service_reply":  # a reply to a customer who wrote first: no consent is needed or created; the sender checks the 24-hour window and the content
        return True, "ok"
    if kind == "occasion":  # a birthday or festival greeting: occasion consent always, plus offers consent while its category is marketing or not yet known
        return consent.has_occasion_consent(db, tenant_id, contact, purpose, bool(template is not None and template.category_confirmed))
    return consent.has_consent(db, tenant_id, contact, purpose)
