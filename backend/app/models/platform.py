"""AI logs, subscriptions, audit logs."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Numeric, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin, utcnow


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


class AICallLedger(IdMixin, Base):
    """One row per model call, written in its own transaction so it survives a rolled-back request. Never holds a prompt or customer text.

    This is what the budgets read. It has no foreign key to tenants on purpose: spend history must outlive a deleted business."""

    __tablename__ = "ai_call_ledger"
    __table_args__ = (Index("ix_ai_call_ledger_created", "created_at"), Index("ix_ai_call_ledger_tenant_created", "tenant_id", "created_at"))

    tenant_id: Mapped[uuid.UUID | None] = mapped_column()  # NULL = a platform-level call
    kind: Mapped[str] = mapped_column(String(32))  # the task
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(80))
    input_tokens: Mapped[int | None] = mapped_column(Integer)  # as the provider reported them (NULL when it reported none)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))  # estimated from the configured prices; NULL = no price known
    status: Mapped[str] = mapped_column(String(16))  # ok | error | blocked
    error_code: Mapped[str | None] = mapped_column(String(32))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    google_location_id: Mapped[uuid.UUID | None] = mapped_column()  # the location the call was for, when it was for one
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column()  # the person who caused it; NULL for scheduled and agent work
    request_id: Mapped[str | None] = mapped_column(String(64))  # one id per model call, so a ledger row can be matched to logs
    retry_count: Mapped[int | None] = mapped_column(SmallInteger)  # 0 for the first call of a task, 1+ for rewrites and second attempts
    cached_tokens: Mapped[int | None] = mapped_column(Integer)  # as the provider reported them; NULL = not reported
    feature: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ApiUsage(IdMixin, Base):
    """One external API call that costs money or is rate-limited (Places searches, Business Profile calls). See services/usage.py for the rules: prices are configured never
    assumed (NULL cost = unpriced), one row per real request, refusals are recorded, retries cannot count twice. No foreign key to tenants on purpose."""

    __tablename__ = "api_usage_ledger"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column()
    google_location_id: Mapped[uuid.UUID | None] = mapped_column()
    user_id: Mapped[uuid.UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    provider: Mapped[str] = mapped_column(String(24))
    operation: Mapped[str] = mapped_column(String(48))
    feature: Mapped[str] = mapped_column(String(32))
    units: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(10))  # ok | error | refused
    reason: Mapped[str | None] = mapped_column(String(200))
    request_id: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(96))
    est_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))  # NULL = no price configured
    priced: Mapped[bool] = mapped_column(Boolean, default=False)
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)


class Subscription(IdMixin, TimestampMixin, Base):
    """Foundational entity only; no billing flow yet (Razorpay is a later phase)."""

    __tablename__ = "subscriptions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), unique=True)
    plan: Mapped[str] = mapped_column(String(32), default="trial")
    status: Mapped[str] = mapped_column(String(24), default="trialing")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    monthly_ai_generations: Mapped[int] = mapped_column(Integer, default=500)  # legacy display total
    review_generations: Mapped[int] = mapped_column(Integer, default=0)  # copied from the plan when it is applied; enforced by the backend
    review_replies: Mapped[int] = mapped_column(Integer, default=0)
    limits: Mapped[dict] = mapped_column(JSONB, default=dict)
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
