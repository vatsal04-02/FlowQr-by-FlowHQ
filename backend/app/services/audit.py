import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog
from app.models.base import utcnow


def audit(
    db: Session,
    *,
    action: str,
    tenant_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: Any = None,
    meta: dict | None = None,
    ip: str | None = None,
) -> None:
    """Append an audit entry in the caller's transaction. Never put secrets in `meta`."""
    db.add(
        AuditLog(
            tenant_id=tenant_id, user_id=user_id, action=action, entity_type=entity_type,
            entity_id=str(entity_id) if entity_id else None, meta=meta or {}, ip=ip, created_at=utcnow(),
        )
    )
