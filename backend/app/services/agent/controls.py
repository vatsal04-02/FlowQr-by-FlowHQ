"""Emergency controls for autonomy.

* PLATFORM emergency stop: an operator flips one switch and no autonomous or approved Google profile write is executed anywhere, and the scheduled
  publishing jobs hold. It is read from the environment (AUTONOMY_EMERGENCY_STOP, needs a restart) OR from the platform_controls table (flipped at runtime from
  the admin endpoint, takes effect on the next job run). Either one is enough. Held work is not lost or failed: it simply waits.
* TENANT switch: agent_settings.autonomy_enabled, plus automatic suspension after repeated failures (executor). Handled in the executor."""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import PlatformControl
from app.models.base import utcnow
from app.services.audit import audit

KEY = "autonomy_emergency_stop"


def emergency_stop(db: Session) -> dict | None:
    """{"on": True, "source", "reason", ...} while execution is stopped, else None."""
    if settings.autonomy_emergency_stop:
        return {"on": True, "source": "environment", "reason": "AUTONOMY_EMERGENCY_STOP is set on this server."}
    row = db.get(PlatformControl, KEY)
    if row is not None and (row.value or {}).get("on"):
        return {"on": True, "source": "admin", "reason": (row.value or {}).get("reason") or "Stopped by a platform administrator.",
                "since": (row.value or {}).get("since"), "by": str(row.updated_by) if row.updated_by else None}
    return None


def set_emergency_stop(db: Session, *, on: bool, user_id: uuid.UUID | None, reason: str | None) -> dict:
    """Turn the runtime stop on or off (caller commits). Audited either way."""
    row = db.get(PlatformControl, KEY)
    now = utcnow()
    value = {"on": on, "reason": (reason or "").strip()[:300], "since": now.isoformat() if on else None}
    if row is None:
        db.add(PlatformControl(key=KEY, value=value, updated_by=user_id, updated_at=now))
    else:
        row.value, row.updated_by, row.updated_at = value, user_id, now
    audit(db, action="autonomy.emergency_stop_on" if on else "autonomy.emergency_stop_off", user_id=user_id, entity_type="platform", meta={"reason": value["reason"]})
    db.flush()  # so the new state can be read back below
    return emergency_stop(db) or {"on": False}
