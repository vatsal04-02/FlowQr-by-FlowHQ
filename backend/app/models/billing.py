"""Billing: plans, payments (subscription vs physical-card kept separate), card orders, webhook idempotency."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Boolean
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin


class BillingPlan(Base):
    __tablename__ = "billing_plans"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)  # essential | growth | multi
    name: Mapped[str] = mapped_column(String(80))
    price_paise: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    interval: Mapped[str] = mapped_column(String(16), default="monthly")
    max_locations: Mapped[int] = mapped_column(Integer)
    monthly_ai_generations: Mapped[int] = mapped_column(Integer)
    max_staff: Mapped[int] = mapped_column(Integer)
    features: Mapped[list] = mapped_column(JSONB, default=list)
    razorpay_plan_id: Mapped[str | None] = mapped_column(String(64))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class CardOrder(IdMixin, TimestampMixin, Base):
    """Physical card purchase. Tracked separately from software subscriptions."""

    __tablename__ = "card_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_card_order_idem"),
        Index("ix_card_orders_tenant", "tenant_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_paise: Mapped[int] = mapped_column(Integer)
    amount_paise: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[str] = mapped_column(String(16), default="created")  # created|paid|processing|shipped|cancelled|failed
    razorpay_order_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    shipping: Mapped[dict] = mapped_column(JSONB, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(80))
    tracking_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class Payment(IdMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (Index("ix_payments_tenant_created", "tenant_id", "created_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))  # subscription | card_order
    status: Mapped[str] = mapped_column(String(16))  # created | authorized | captured | failed | refunded
    amount_paise: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    razorpay_order_id: Mapped[str | None] = mapped_column(String(64))
    razorpay_subscription_id: Mapped[str | None] = mapped_column(String(64))
    razorpay_invoice_id: Mapped[str | None] = mapped_column(String(64))
    card_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("card_orders.id", ondelete="SET NULL"))
    method: Mapped[str | None] = mapped_column(String(24))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_description: Mapped[str | None] = mapped_column(Text)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)


class WebhookEvent(IdMixin, Base):
    """Idempotency + audit for inbound provider webhooks. Not tenant-scoped (written before tenant is known)."""

    __tablename__ = "webhook_events"

    provider: Mapped[str] = mapped_column(String(16))
    event_id: Mapped[str] = mapped_column(String(120), unique=True)
    event_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="received")  # received | processed | ignored | error
    error: Mapped[str | None] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
