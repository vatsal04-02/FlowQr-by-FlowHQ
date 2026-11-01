import time
import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AIGenerationLog, Subscription
from app.models.base import utcnow


def month_start() -> datetime:
    n = utcnow()
    return datetime(n.year, n.month, 1, tzinfo=timezone.utc)


def usage_this_month(db: Session, tenant_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count()).select_from(AIGenerationLog).where(
            AIGenerationLog.tenant_id == tenant_id, AIGenerationLog.created_at >= month_start())
    ) or 0


def quota_exceeded(db: Session, tenant_id: uuid.UUID) -> bool:
    sub = db.scalar(select(Subscription).where(Subscription.tenant_id == tenant_id))
    limit = sub.monthly_ai_generations if sub else 100
    return usage_this_month(db, tenant_id) >= limit


def log_generation(db: Session, *, tenant_id, kind, provider, model, language, input_chars, output_chars, status,
                   started: float, location_id=None, card_id=None, error: str | None = None) -> None:
    db.add(AIGenerationLog(
        tenant_id=tenant_id, location_id=location_id, card_id=card_id, kind=kind, provider=provider, model=model,
        language=language, input_chars=input_chars, output_chars=output_chars, status=status,
        error=(error or None) and error[:500], latency_ms=int((time.monotonic() - started) * 1000), created_at=utcnow(),
    ))
