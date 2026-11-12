"""AI logs, subscriptions, audit logs."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin


class AIGenerationLog(IdMixin, Base):
    """Usage log. Deliberately stores sizes only, never customer text."""

    __tablename__ = "ai_generation_logs"
    __table_args__ = (Index("ix_ailog_tenant_created", "tenant_id", "created_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    card_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("qr_cards.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(24))  # review_assist | reply_draft
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(80))
    language: Mapped[str | None] = mapped_column(String(16))
    input_chars: Mapped[int] = mapped_column(Integer, default=0)
    output_chars: Mapped[int] = mapped_column(Integer, default=0)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)  # as reported by the provider (NULL when it reports none)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    model_calls: Mapped[int | None] = mapped_column(Integer)  # provider calls made for this one customer request (writes + fact-checks)
    attempts: Mapped[int | None] = mapped_column(Integer)  # write attempts (1 = no retry needed)
    rejects_rules: Mapped[int | None] = mapped_column(Integer)  # attempts rejected by the deterministic checks
    rejects_factcheck: Mapped[int | None] = mapped_column(Integer)  # attempts rejected by the AI fact-check
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))  # as reported by the provider (OpenRouter), NULL otherwise
    status: Mapped[str] = mapped_column(String(16))  # ok | error | rejected
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Subscription(IdMixin, TimestampMixin, Base):
    """Foundational entity only; no billing flow yet (Razorpay is a later phase)."""

    __tablename__ = "subscriptions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), unique=True)
    plan: Mapped[str] = mapped_column(String(32), default="trial")
    status: Mapped[str] = mapped_column(String(24), default="trialing")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    monthly_ai_generations: Mapped[int] = mapped_column(Integer, default=500)
    max_locations: Mapped[int] = mapped_column(Integer, default=3)
    max_staff: Mapped[int] = mapped_column(Integer, default=10)
    features: Mapped[list] = mapped_column(JSONB, default=list)  # e.g. ["gbp_posts", "gbp_media", "gbp_performance"]
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    past_due_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pending_plan: Mapped[str | None] = mapped_column(String(32))  # scheduled downgrade/upgrade at cycle end
    source: Mapped[str] = mapped_column(String(16), default="trial")  # trial | razorpay | manual
    razorpay_subscription_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(IdMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (Index("ix_audit_tenant_created", "tenant_id", "created_at"),)

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="SET NULL"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str | None] = mapped_column(String(48))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
