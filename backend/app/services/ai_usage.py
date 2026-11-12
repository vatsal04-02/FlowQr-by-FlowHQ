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
    """True when AI must not be used: subscription inactive or monthly quota consumed."""
    from app.services import entitlements as ent

    e = ent.for_tenant(db, tenant_id)
    return (not e.active) or usage_this_month(db, tenant_id) >= e.monthly_ai_generations


def log_generation(db: Session, *, tenant_id, kind, provider, model, language, input_chars, output_chars, status,
                   started: float, location_id=None, card_id=None, error: str | None = None, usage: dict | None = None,
                   stats: dict | None = None) -> None:
    """`usage` is the provider's running total ({"prompt_tokens", "completion_tokens", "calls", "cost", "model"}), if it reports one.
    `stats` is generate_review's {"attempts", "rejects_rules", "rejects_factcheck"}. Failed and rejected attempts that still consumed
    tokens are logged with them. Never pass customer text here."""
    used = usage if usage and usage.get("calls") else None
    stats = stats or {}
    cost = (used or {}).get("cost")
    db.add(AIGenerationLog(
        tenant_id=tenant_id, location_id=location_id, card_id=card_id, kind=kind, provider=provider, model=(used or {}).get("model") or model,
        language=language, input_chars=input_chars, output_chars=output_chars, status=status,
        prompt_tokens=used["prompt_tokens"] if used else None, completion_tokens=used["completion_tokens"] if used else None,
        model_calls=used["calls"] if used else None, attempts=stats.get("attempts"), rejects_rules=stats.get("rejects_rules"),
        rejects_factcheck=stats.get("rejects_factcheck"), cost_usd=round(cost, 6) if cost else None,
        error=(error or None) and error[:500], latency_ms=int((time.monotonic() - started) * 1000), created_at=utcnow(),
    ))
