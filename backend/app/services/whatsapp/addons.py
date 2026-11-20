"""WhatsApp add-on entitlements, recorded by hand by a FlowQR administrator. No billing is connected and no existing plan, price or Cashfree setting is read or changed here: the add-on is a
separate row (`tenant_addons`) beside the subscription. Meta's per-message charges are never part of it."""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Tenant, User
from app.models.base import utcnow
from app.models.whatsapp import ADDON_KEYS, TenantAddon
from app.services.audit import audit
from app.services.whatsapp import WaError, rules


def active_addon(db: Session, tenant_id: uuid.UUID) -> TenantAddon | None:
    return db.scalar(select(TenantAddon).where(TenantAddon.tenant_id == tenant_id, TenantAddon.status == "active", TenantAddon.addon_key.like("whatsapp_%")))


def tier(addon: TenantAddon | None) -> dict | None:
    if addon is None:
        return None
    t = rules.ADDON_TIERS[addon.addon_key]
    return {"key": addon.addon_key, **t, "since": addon.started_at}


def occasions_allowed(db: Session, tenant_id: uuid.UUID) -> bool:
    """Birthday and festival greetings are part of the Growth and Pro add-ons."""
    from app.core.config import settings
    if not settings.whatsapp_require_addon:
        return True
    t = tier(active_addon(db, tenant_id))
    return bool(t and t.get("occasions"))


def bookings_allowed(db: Session, tenant_id: uuid.UUID) -> bool:
    """Appointment booking and reminders are part of the Growth and Pro add-ons."""
    from app.core.config import settings
    if not settings.whatsapp_require_addon:
        return True
    t = tier(active_addon(db, tenant_id))
    return bool(t and t.get("bookings"))


def integrations_allowed(db: Session, tenant_id: uuid.UUID) -> bool:
    """API keys, the inbound API and outbound webhooks are part of the Pro add-on only."""
    from app.core.config import settings
    if not settings.whatsapp_require_addon:
        return True
    t = tier(active_addon(db, tenant_id))
    return bool(t and t.get("integrations"))


def click_tracking_allowed(db: Session, tenant_id: uuid.UUID) -> bool:
    """Counting link clicks is part of the Pro add-on only."""
    from app.core.config import settings
    if not settings.whatsapp_require_addon:
        return True
    t = tier(active_addon(db, tenant_id))
    return bool(t and t.get("click_tracking"))


def set_addon(db: Session, admin: User, tenant: Tenant, addon_key: str | None, reason: str, ip: str | None = None) -> TenantAddon | None:
    """Switch a business's WhatsApp tier (or turn it off with None). Every change needs a written reason and is audited. Ending an add-on never deletes the business's contacts, consents or
    messages; it only stops new connections and (in later phases) new sends."""
    reason = " ".join((reason or "").split())
    if len(reason) < 5:
        raise WaError(422, "reason_required", "Write a short reason (for example: paid 499 by UPI on 12 Nov).")
    if addon_key is not None and addon_key not in ADDON_KEYS:
        raise WaError(422, "invalid_addon", "Unknown add-on.")
    now = utcnow()
    current = active_addon(db, tenant.id)
    if current is not None and current.addon_key == addon_key:
        return current
    if current is not None:
        current.status, current.ended_at = "ended", now
        db.flush()
    new = None
    if addon_key is not None:
        new = TenantAddon(tenant_id=tenant.id, addon_key=addon_key, status="active", reason=reason[:300], started_at=now, granted_by=admin.id)
        db.add(new)
        db.flush()
    audit(db, action="admin.whatsapp_addon", tenant_id=tenant.id, user_id=admin.id, entity_type="tenant_addon", entity_id=(new.id if new else current.id if current else None),
          meta={"from": current.addon_key if current else None, "to": addon_key, "reason": reason[:200]}, ip=ip)
    return new
