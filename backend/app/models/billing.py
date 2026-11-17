"""Billing: plans, payments (subscription vs physical-card kept separate), card orders, webhook idempotency."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Boolean, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin


class BillingPlan(Base):
    __tablename__ = "billing_plans"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)  # starter | growth | pro (essential and multi are retired, kept only for existing subscribers)
    name: Mapped[str] = mapped_column(String(80))
    price_paise: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    interval: Mapped[str] = mapped_column(String(16), default="monthly")
    max_locations: Mapped[int] = mapped_column(Integer)
    monthly_ai_generations: Mapped[int] = mapped_column(Integer)  # legacy display total (review generations + replies); quotas below are what is enforced
    review_generations: Mapped[int] = mapped_column(Integer, default=0)  # customer review-writing assistant: its own monthly allowance
    review_replies: Mapped[int] = mapped_column(Integer, default=0)  # AI review replies: a separate allowance, never pooled with the one above
    limits: Mapped[dict] = mapped_column(JSONB, default=dict)  # other plan limits, e.g. {"geo": {...}}; a missing value means NOT CONFIGURED (feature stays off)
    max_staff: Mapped[int] = mapped_column(Integer)
    features: Mapped[list] = mapped_column(JSONB, default=list)
    razorpay_plan_id: Mapped[str | None] = mapped_column(String(64))
    cashfree_plan_id: Mapped[str | None] = mapped_column(String(40), unique=True)
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
    offer_code: Mapped[str | None] = mapped_column(String(16))  # which bundle was bought (one | two), when it was a bundle
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
    provider: Mapped[str | None] = mapped_column(String(12))  # cashfree | razorpay (NULL on old rows)
    cashfree_payment_id: Mapped[str | None] = mapped_column(String(64), unique=True)  # our merchant payment id, echoed by Cashfree
    cashfree_cf_payment_id: Mapped[str | None] = mapped_column(String(32))
    payment_type: Mapped[str | None] = mapped_column(String(8))  # AUTH (the refundable authorisation) | CHARGE (a monthly charge)
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    card_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("card_orders.id", ondelete="SET NULL"))
    method: Mapped[str | None] = mapped_column(String(24))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_description: Mapped[str | None] = mapped_column(Text)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)


class PrepaidOrder(IdMixin, TimestampMixin, Base):
    """One attempt to buy a prepaid term (Cashfree Payment Gateway order). The amount is fixed by the SERVER from its own price list when the row is created; nothing the browser sends changes it.
    A row never grants access by itself: access is granted only when Cashfree reports the order PAID for exactly this amount (services/prepaid.py)."""

    __tablename__ = "prepaid_orders"
    __table_args__ = (Index("ix_prepaid_orders_tenant", "tenant_id", "created_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    plan_code: Mapped[str] = mapped_column(String(32))
    months: Mapped[int] = mapped_column(Integer)
    amount_paise: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    status: Mapped[str] = mapped_column(String(16), default="created")  # created | paid | failed | expired | mismatch
    order_id: Mapped[str] = mapped_column(String(40), unique=True)  # OUR id, sent to Cashfree as order_id
    cf_order_id: Mapped[str | None] = mapped_column(String(32))
    cf_payment_id: Mapped[str | None] = mapped_column(String(32))
    payment_method: Mapped[str | None] = mapped_column(String(24))  # only the kind (upi, card, netbanking...): never a number or an id
    failure_reason: Mapped[str | None] = mapped_column(String(300))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    list_price_paise: Mapped[int | None] = mapped_column(Integer)  # the permanent list price at the time, recorded SEPARATELY from what was charged (`amount_paise`)
    override_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("prepaid_price_overrides.id", ondelete="SET NULL"))  # set only when a temporary override set the amount


class PrepaidPriceOverride(IdMixin, Base):
    """A temporary price for ONE business, ONE plan and term, ONCE, until `expires_at`. Created only by the operator CLI (app/prepaid_cli.py); no API route creates or lists one for other businesses.
    The permanent price list is never edited. It can only lower a price (database check), is consumed by the first PAID order that used it, and can be revoked."""

    __tablename__ = "prepaid_price_overrides"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    plan_code: Mapped[str] = mapped_column(String(32))
    months: Mapped[int] = mapped_column(Integer)
    amount_paise: Mapped[int] = mapped_column(Integer)
    list_price_paise: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(60), default="Test price")
    reason: Mapped[str] = mapped_column(String(300))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("prepaid_orders.id", ondelete="SET NULL"))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
    subscription_ref: Mapped[str | None] = mapped_column(String(250))  # our subscription id from the payload (a hint only; the row is looked up by it, nothing else is trusted)
    payment_ref: Mapped[str | None] = mapped_column(String(64))
    payload_hash: Mapped[str | None] = mapped_column(String(64))  # sha256 of the raw body: proves what arrived without storing customer details
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(300))  # a safe, short reason: never a payload, a secret or a customer detail
    provider_event_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SubscriptionEvent(IdMixin, Base):
    """Append-only history of what happened to a business's subscription: who or what changed it, from what, to what. Never edited; read by support and finance."""

    __tablename__ = "subscription_events"
    __table_args__ = (Index("ix_subscription_events_tenant", "tenant_id", "created_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(32))  # trial_started | activated | plan_changed | status_changed | cancel_requested | canceled | expired | past_due | payment_failed | renewed | refunded | promo_granted | promo_ended | promo_revoked | admin_override
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str | None] = mapped_column(String(24))
    from_plan: Mapped[str | None] = mapped_column(String(32))
    to_plan: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(16))  # webhook | user | admin | system | promo
    ref: Mapped[str | None] = mapped_column(String(120))  # provider event id, payment id, card order id...
    meta: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)


class PromotionalGrant(IdMixin, Base):
    """Free access that was not paid for as a subscription (today: the Growth month that comes with a physical-card purchase). Recorded separately so it is never
    counted as MRR, and so a refund of the card can end it."""

    __tablename__ = "promotional_grants"
    __table_args__ = (UniqueConstraint("card_order_id", name="uq_promo_grant_card_order"), Index("ix_promo_grants_tenant", "tenant_id", "status"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(24), default="card_purchase")
    plan: Mapped[str] = mapped_column(String(32), default="growth")
    status: Mapped[str] = mapped_column(String(12), default="active")  # active | ended | revoked
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    card_order_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("card_orders.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    note: Mapped[str | None] = mapped_column(Text)
