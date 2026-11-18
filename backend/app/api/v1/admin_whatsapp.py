"""WhatsApp add-on administration (platform administrators only). The add-on is recorded by hand: no billing, no plan change, no Cashfree. Works while WHATSAPP_ENABLED is false so a tier can be
recorded before launch."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.deps import AuthContext, require_platform_admin
from app.core.rate_limit import client_ip
from app.models import Tenant
from app.services.whatsapp import WaError, addons, connection, consent, rules

router = APIRouter(prefix="/admin", tags=["admin-whatsapp"])


class AddonIn(BaseModel):
    addon_key: str | None = Field(default=None, max_length=24)
    reason: str = Field(min_length=5, max_length=300)


def _tenant(ctx: AuthContext, tenant_id: uuid.UUID) -> Tenant:
    t = ctx.db.get(Tenant, tenant_id)
    if t is None:
        raise HTTPException(status_code=404, detail="Business not found")
    return t


@router.get("/tenants/{tenant_id}/whatsapp")
def summary(tenant_id: uuid.UUID, ctx: AuthContext = Depends(require_platform_admin)):
    t = _tenant(ctx, tenant_id)
    return {"enabled": settings.whatsapp_enabled, "addon": addons.tier(addons.active_addon(ctx.db, t.id)), "tiers": [{"key": k, **v} for k, v in rules.ADDON_TIERS.items()],
            "connection": connection.serialize(connection.live_connection(ctx.db, t.id)), "counts": consent.counts(ctx.db, t.id)}


@router.put("/tenants/{tenant_id}/whatsapp-addon")
def set_addon(tenant_id: uuid.UUID, body: AddonIn, request: Request, ctx: AuthContext = Depends(require_platform_admin)):
    t = _tenant(ctx, tenant_id)
    try:
        addons.set_addon(ctx.db, ctx.user, t, body.addon_key, body.reason, client_ip(request))
        ctx.db.commit()
    except WaError as exc:
        ctx.db.rollback()
        raise HTTPException(status_code=exc.status, detail=exc.detail())
    return {"addon": addons.tier(addons.active_addon(ctx.db, t.id))}
