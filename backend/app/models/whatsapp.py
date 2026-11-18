"""WhatsApp automation, Phase 1 foundation: a business's own connection to the official Meta Cloud API, the people it may message, the consent behind each message, template records,
delivery records, the webhook event log, and the manually recorded add-on. Nothing here sends a message (Phase 2).

Every table carries tenant_id with forced row-level security (migration 0048). Access tokens are stored encrypted (Fernet, TOKEN_ENCRYPTION_KEY) in `access_token_enc` and are never returned by an
API, exported or logged."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin


def _in(col: str, values) -> str:
    return f"{col} in ({', '.join(repr(v) for v in values)})"


CONNECTION_STATUSES = ("pending", "connected", "needs_attention", "disconnected")
WEBHOOK_STATUSES = ("unknown", "subscribed", "failed")
PURPOSES = ("marketing", "utility")
CONSENT_SOURCES = ("qr_page", "website_form", "customer_message", "owner_entry", "csv_import", "admin_entry")
CUSTOMER_SOURCES = ("qr_page", "website_form", "customer_message")  # the customer did it themselves: the only sources that can lift an opt-out
TEMPLATE_CATEGORIES = ("marketing", "utility", "authentication")
TEMPLATE_STATUSES = ("pending", "approved", "rejected", "paused", "disabled")
MESSAGE_DIRECTIONS = ("outbound", "inbound")
DELIVERY_STATUSES = ("queued", "sent", "delivered", "read", "failed")
EVENT_STATUSES = ("received", "processed", "ignored", "failed")
ADDON_KEYS = ("whatsapp_starter", "whatsapp_growth", "whatsapp_pro")
ADDON_STATUSES = ("active", "ended")


class WhatsAppConnection(IdMixin, TimestampMixin, Base):
    """One business's connection to ONE WhatsApp Business number. `pending` rows are an Embedded Signup attempt in progress (the hashed one-time `state`, no phone number yet); the callback must
    present the state it was given. At most one live (non-disconnected) connection per business, and a phone_number_id can belong to at most one business at a time: that mapping is the only way a
    webhook or a send is ever attributed to a business."""

    __tablename__ = "whatsapp_connections"
    __table_args__ = (
        CheckConstraint(_in("status", CONNECTION_STATUSES), name="ck_wa_conn_status"),
        CheckConstraint(_in("webhook_status", WEBHOOK_STATUSES), name="ck_wa_conn_webhook"),
        Index("uq_wa_conn_tenant_live", "tenant_id", unique=True, postgresql_where=text("status <> 'disconnected'")),
        Index("uq_wa_conn_phone_live", "phone_number_id", unique=True, postgresql_where=text("status <> 'disconnected' AND phone_number_id IS NOT NULL")),
        Index("ix_wa_conn_state", "state_hash"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    waba_id: Mapped[str | None] = mapped_column(String(40))
    phone_number_id: Mapped[str | None] = mapped_column(String(40))
    display_phone_number: Mapped[str | None] = mapped_column(String(32))
    verified_name: Mapped[str | None] = mapped_column(String(160))
    quality_rating: Mapped[str | None] = mapped_column(String(16))  # GREEN | YELLOW | RED as Meta reports it
    is_test_number: Mapped[bool] = mapped_column(Boolean, default=False)  # a Meta test number (development mode)
    access_token_enc: Mapped[str | None] = mapped_column(Text)  # Fernet ciphertext; never leaves the server
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # NULL = Meta reports no expiry
    token_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    webhook_status: Mapped[str] = mapped_column(String(12), default="unknown")
    attention_reason: Mapped[str | None] = mapped_column(String(200))  # plain words: why the owner must act
    state_hash: Mapped[str | None] = mapped_column(String(64))  # sha256 of the one-time Embedded Signup state
    state_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WhatsAppContact(IdMixin, TimestampMixin, Base):
    """A person a business may want to message. Holds the least personal data that works: a number, an optional first name, free tags. Having a contact is NOT consent: consent is a separate,
    append-only record (WhatsAppConsent). Contacts are never created from review submissions or imported silently."""

    __tablename__ = "whatsapp_contacts"
    __table_args__ = (UniqueConstraint("tenant_id", "phone", name="uq_wa_contact_phone"), Index("ix_wa_contact_tenant_created", "tenant_id", "created_at"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    phone: Mapped[str] = mapped_column(String(20))  # E.164
    customer_name: Mapped[str | None] = mapped_column(String(120))
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    source: Mapped[str] = mapped_column(String(18))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    marketing_opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # set by an opt-out; cleared only by a customer-originated new consent


class WhatsAppConsent(IdMixin, Base):
    """One consent, for ONE purpose, exactly as it was worded. Append-only in spirit: the application role may only INSERT, and UPDATE the revocation columns (column-level grant), so the wording,
    source and time of a consent can never be edited afterwards. A new consent after a withdrawal is a new row. At most one active row per contact and purpose."""

    __tablename__ = "whatsapp_consents"
    __table_args__ = (
        CheckConstraint(_in("purpose", PURPOSES), name="ck_wa_consent_purpose"),
        CheckConstraint(_in("source", CONSENT_SOURCES), name="ck_wa_consent_source"),
        Index("uq_wa_consent_active", "contact_id", "purpose", unique=True, postgresql_where=text("revoked_at IS NULL")),
        Index("ix_wa_consent_tenant", "tenant_id", "granted_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("whatsapp_contacts.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(18))
    wording_version: Mapped[str] = mapped_column(String(24))
    wording_text: Mapped[str] = mapped_column(String(600))  # what the customer (or the owner, on their behalf) was shown, verbatim
    evidence: Mapped[str | None] = mapped_column(String(400))  # for owner entry and CSV: how the owner says consent was obtained
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    granted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_source: Mapped[str | None] = mapped_column(String(24))  # customer_stop | owner | admin | erasure
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class WhatsAppSuppression(IdMixin, Base):
    """A number that opted out of a business's marketing. Kept as a keyed hash (not the number) so an erased contact can never be re-added and messaged by mistake."""

    __tablename__ = "whatsapp_suppressions"
    __table_args__ = (UniqueConstraint("tenant_id", "phone_hash", name="uq_wa_suppression"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    phone_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(String(24))  # customer_stop | owner | admin
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WhatsAppTemplate(IdMixin, TimestampMixin, Base):
    """A message template as Meta knows it. Only an `approved` template can ever be sent, and only in its own category (Phase 2 enforces both)."""

    __tablename__ = "whatsapp_templates"
    __table_args__ = (
        CheckConstraint(_in("category", TEMPLATE_CATEGORIES), name="ck_wa_template_category"),
        CheckConstraint(_in("approval_status", TEMPLATE_STATUSES), name="ck_wa_template_status"),
        UniqueConstraint("connection_id", "template_name", "language", name="uq_wa_template_name"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("whatsapp_connections.id", ondelete="CASCADE"))
    meta_template_id: Mapped[str | None] = mapped_column(String(40))
    template_name: Mapped[str] = mapped_column(String(80))
    language: Mapped[str] = mapped_column(String(12))
    category: Mapped[str] = mapped_column(String(16))
    approval_status: Mapped[str] = mapped_column(String(10), default="pending")
    body_text: Mapped[str | None] = mapped_column(String(1100))
    variable_schema: Mapped[list] = mapped_column(JSONB, default=list)
    rejection_reason: Mapped[str | None] = mapped_column(String(300))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WhatsAppMessage(IdMixin, TimestampMixin, Base):
    """A message record. Phase 1 only RECEIVES status updates for these (the table is empty until Phase 2 sends); statuses only move forward: sent, delivered, read; failed can follow any."""

    __tablename__ = "whatsapp_messages"
    __table_args__ = (
        CheckConstraint(_in("direction", MESSAGE_DIRECTIONS), name="ck_wa_msg_direction"),
        CheckConstraint(_in("delivery_status", DELIVERY_STATUSES), name="ck_wa_msg_status"),
        Index("uq_wa_msg_meta", "phone_number_id", "meta_message_id", unique=True, postgresql_where=text("meta_message_id IS NOT NULL")),
        Index("ix_wa_msg_tenant_created", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    connection_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("whatsapp_connections.id", ondelete="SET NULL"))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("whatsapp_contacts.id", ondelete="SET NULL"))
    phone_number_id: Mapped[str] = mapped_column(String(40))
    meta_message_id: Mapped[str | None] = mapped_column(String(120))
    direction: Mapped[str] = mapped_column(String(8), default="outbound")
    category: Mapped[str | None] = mapped_column(String(16))
    template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("whatsapp_templates.id", ondelete="SET NULL"))
    delivery_status: Mapped[str] = mapped_column(String(10), default="queued")
    error_code: Mapped[str | None] = mapped_column(String(20))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WhatsAppWebhookEvent(IdMixin, Base):
    """A Meta webhook delivery that passed signature verification. The body is stored SANITISED (statuses and the few inbound fields the opt-out rule needs; no names, no message text beyond a
    short keyword check, no media), keyed by the SHA-256 of the raw body so a redelivery is recognised and processed once. `tenant_id` is filled only by the verified phone_number_id mapping."""

    __tablename__ = "whatsapp_webhook_events"
    __table_args__ = (
        CheckConstraint(_in("status", EVENT_STATUSES), name="ck_wa_event_status"),
        UniqueConstraint("payload_sha256", name="uq_wa_event_payload"),
        Index("ix_wa_event_status_received", "status", "received_at"),
    )

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    phone_number_id: Mapped[str | None] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(10), default="received")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(300))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TenantAddon(IdMixin, TimestampMixin, Base):
    """A paid add-on recorded BY HAND by a FlowQR administrator (no billing is connected, Cashfree is untouched). The three WhatsApp tiers are one family: at most one active."""

    __tablename__ = "tenant_addons"
    __table_args__ = (
        CheckConstraint(_in("addon_key", ADDON_KEYS), name="ck_tenant_addon_key"),
        CheckConstraint(_in("status", ADDON_STATUSES), name="ck_tenant_addon_status"),
        Index("uq_tenant_addon_active_family", "tenant_id", unique=True, postgresql_where=text("status = 'active' AND addon_key LIKE 'whatsapp_%'")),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    addon_key: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(8), default="active")
    reason: Mapped[str] = mapped_column(String(300))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    granted_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
