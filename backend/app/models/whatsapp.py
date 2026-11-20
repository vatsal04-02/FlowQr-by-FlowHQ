"""WhatsApp automation, Phase 1 foundation: a business's own connection to the official Meta Cloud API, the people it may message, the consent behind each message, template records,
delivery records, the webhook event log, and the manually recorded add-on. Nothing here sends a message (Phase 2).

Every table carries tenant_id with forced row-level security (migration 0048). Access tokens are stored encrypted (Fernet, TOKEN_ENCRYPTION_KEY) in `access_token_enc` and are never returned by an
API, exported or logged."""
import uuid
from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, SmallInteger, String, Text, Time, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin, utcnow


def _in(col: str, values) -> str:
    return f"{col} in ({', '.join(repr(v) for v in values)})"


CONNECTION_STATUSES = ("pending", "connected", "needs_attention", "disconnected")
WEBHOOK_STATUSES = ("unknown", "subscribed", "failed")
PURPOSES = ("marketing", "utility", "occasion")  # occasion = birthday and festival greetings, a consent of its own
CONSENT_SOURCES = ("qr_page", "website_form", "customer_message", "owner_entry", "csv_import", "admin_entry", "qr_click_to_chat", "keyword_opt_in", "whatsapp_booking")
CUSTOMER_SOURCES = ("qr_page", "website_form", "customer_message", "qr_click_to_chat", "keyword_opt_in")  # the customer did it themselves: the only sources that can lift an opt-out
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
    __table_args__ = (UniqueConstraint("tenant_id", "phone", name="uq_wa_contact_phone"), Index("ix_wa_contact_tenant_created", "tenant_id", "created_at"),
                      CheckConstraint("(birth_day IS NULL) = (birth_month IS NULL)", name="ck_wa_contact_birth_pair"),
                      CheckConstraint("birth_month IS NULL OR (birth_month BETWEEN 1 AND 12 AND birth_day BETWEEN 1 AND 31 AND NOT (birth_month IN (4, 6, 9, 11) AND birth_day > 30) AND NOT (birth_month = 2 AND birth_day > 29))", name="ck_wa_contact_birth_valid"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    phone: Mapped[str] = mapped_column(String(20))  # E.164
    customer_name: Mapped[str | None] = mapped_column(String(120))
    tags: Mapped[list] = mapped_column(JSONB, default=list)
    source: Mapped[str] = mapped_column(String(18))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    marketing_opted_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # set by an opt-out; cleared only by a customer-originated new consent
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))  # optional: which branch this customer belongs to (location-specific offers)
    last_replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # when the customer last wrote to the business (not STOP). A time only: no message text is kept
    last_visit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # when the owner last marked a visit as done
    last_enquiry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # when this customer last sent a website enquiry that came with a WhatsApp agreement
    birth_day: Mapped[int | None] = mapped_column(SmallInteger)  # optional birth day and month, never a year; used only for a birthday greeting the customer agreed to
    birth_month: Mapped[int | None] = mapped_column(SmallInteger)


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
    category_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)  # True only once Meta's own status listing has reported the category; until then the category is not known
    simple: Mapped[bool] = mapped_column(Boolean, default=True)  # a text body only (no header, media or button variables): the only kind a campaign can fill with plain text


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
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("whatsapp_campaigns.id", ondelete="SET NULL"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("whatsapp_automation_runs.id", ondelete="SET NULL"))
    idempotency_key: Mapped[str | None] = mapped_column(String(200))  # one send per key per business: a retry or a re-run can never send twice
    est_rate: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))  # the rate in force when it was sent: an ESTIMATE of Meta's charge, not an invoice
    kind: Mapped[str | None] = mapped_column(String(16))  # optin_confirm | (later) occasion: sent through the same gate, but not counted by the offer-frequency gap


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


AUTOMATION_KEYS = ("review_followup", "enquiry_followup", "birthday", "festival")
AUTOMATION_STATUSES = ("off", "on", "paused")
RUN_STATUSES = ("scheduled", "sending", "sent", "skipped", "failed", "cancelled")
CAMPAIGN_STATUSES = ("draft", "scheduled", "sending", "paused", "done", "cancelled")
RECIPIENT_STATUSES = ("pending", "sent", "skipped", "failed")
RATE_CATEGORIES = ("marketing", "utility", "authentication", "service")


class WhatsAppRate(IdMixin, Base):
    """A dated Meta per-message rate. Global data (not per business). Rates change over time and by country, so they live here and never in code; a row is never edited, a new
    effective date is added. `verified` is false until an administrator has checked the number against Meta's own rate card."""

    __tablename__ = "whatsapp_rates"
    __table_args__ = (CheckConstraint(_in("category", RATE_CATEGORIES), name="ck_wa_rate_category"), CheckConstraint("free_per_number_month >= 0", name="ck_wa_rate_free"),
                      UniqueConstraint("country", "category", "effective_from", name="uq_wa_rate"))

    country: Mapped[str] = mapped_column(String(2))
    category: Mapped[str] = mapped_column(String(16))
    rate: Mapped[Decimal] = mapped_column(Numeric(10, 4))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    effective_from: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(300))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)  # as written with the row; the price screen shows the LATEST WhatsAppRateVerification instead
    free_per_number_month: Mapped[int] = mapped_column(Integer, default=0)  # messages of this category Meta gives free per number per month (0 = none)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WhatsAppRateVerification(IdMixin, Base):
    """Append-only: an administrator's check of one rate row against Meta's own rate card. The rate row is never touched; the newest check for a row is the one that counts."""

    __tablename__ = "whatsapp_rate_verifications"

    rate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("whatsapp_rates.id", ondelete="RESTRICT"))
    verified: Mapped[bool] = mapped_column(Boolean)
    note: Mapped[str] = mapped_column(String(300))
    verified_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WhatsAppAutomation(IdMixin, TimestampMixin, Base):
    __tablename__ = "whatsapp_automations"
    __table_args__ = (CheckConstraint(_in("automation_key", AUTOMATION_KEYS), name="ck_wa_auto_key"), CheckConstraint(_in("status", AUTOMATION_STATUSES), name="ck_wa_auto_status"),
                      UniqueConstraint("tenant_id", "automation_key", name="uq_wa_auto"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    automation_key: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(8), default="off")
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class WhatsAppAutomationRun(IdMixin, TimestampMixin, Base):
    """One scheduled send caused by one trigger. The idempotency key (automation + trigger + step) is unique: a trigger that fires twice, or a worker that runs twice, sends once."""

    __tablename__ = "whatsapp_automation_runs"
    __table_args__ = (CheckConstraint(_in("status", RUN_STATUSES), name="ck_wa_run_status"), UniqueConstraint("idempotency_key", name="uq_wa_run_idem"), Index("ix_wa_run_due", "status", "scheduled_at"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    automation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("whatsapp_automations.id", ondelete="CASCADE"))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("whatsapp_contacts.id", ondelete="SET NULL"))
    step: Mapped[str] = mapped_column(String(16))  # request | ack | followup
    trigger_ref: Mapped[str] = mapped_column(String(120))
    idempotency_key: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(10), default="scheduled")
    reason: Mapped[str | None] = mapped_column(String(60))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    context: Mapped[dict] = mapped_column(JSONB, default=dict)  # what the send needs and nothing more (a first name, an enquiry id)


class WhatsAppCampaign(IdMixin, TimestampMixin, Base):
    __tablename__ = "whatsapp_campaigns"
    __table_args__ = (CheckConstraint(_in("status", CAMPAIGN_STATUSES), name="ck_wa_campaign_status"), Index("ix_wa_campaign_due", "status", "scheduled_at"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    template_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("whatsapp_templates.id", ondelete="SET NULL"))
    audience: Mapped[dict] = mapped_column(JSONB, default=dict)
    variables: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(10), default="draft")
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_recipients: Mapped[int | None] = mapped_column(Integer)
    approved_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))  # the ESTIMATE the owner saw and approved
    approved_price: Mapped[dict | None] = mapped_column(JSONB)  # the price it used: rate, the date that price took effect, and whether it was verified at the time. Fixed at approval.
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class WhatsAppCampaignRecipient(IdMixin, Base):
    __tablename__ = "whatsapp_campaign_recipients"
    __table_args__ = (CheckConstraint(_in("status", RECIPIENT_STATUSES), name="ck_wa_recipient_status"), UniqueConstraint("campaign_id", "contact_id", name="uq_wa_campaign_recipient"),
                      Index("ix_wa_recipient_pending", "campaign_id", "status"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("whatsapp_campaigns.id", ondelete="CASCADE"))
    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("whatsapp_contacts.id", ondelete="CASCADE"))
    status: Mapped[str] = mapped_column(String(10), default="pending")
    reason: Mapped[str | None] = mapped_column(String(60))
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("whatsapp_messages.id", ondelete="SET NULL"))


OPTIN_PURPOSES = ("utility", "marketing", "both")


class WhatsAppOptinSettings(IdMixin, TimestampMixin, Base):
    """A business's WhatsApp opt-in without a phone number on the page: a short code that proves a click came from its QR page, whether the page offers the button, and what it asks for."""

    __tablename__ = "whatsapp_optin_settings"
    __table_args__ = (CheckConstraint(_in("purpose", OPTIN_PURPOSES), name="ck_wa_optin_purpose"), UniqueConstraint("tenant_id", name="uq_wa_optin_tenant"), UniqueConstraint("code", name="uq_wa_optin_code"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(10))
    qr_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    purpose: Mapped[str] = mapped_column(String(10), default="utility")
    confirm_reply: Mapped[bool] = mapped_column(Boolean, default=True)


class WhatsAppOptinKeyword(IdMixin, TimestampMixin, Base):
    """A word a customer can text to the business's number to opt in. At most 5 per business (enforced in the service)."""

    __tablename__ = "whatsapp_optin_keywords"
    __table_args__ = (CheckConstraint(_in("purpose", OPTIN_PURPOSES), name="ck_wa_keyword_purpose"), CheckConstraint("keyword = lower(keyword)", name="ck_wa_keyword_lower"),
                      UniqueConstraint("tenant_id", "keyword", name="uq_wa_keyword"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    keyword: Mapped[str] = mapped_column(String(20))
    purpose: Mapped[str] = mapped_column(String(10), default="utility")
    confirm_reply: Mapped[bool] = mapped_column(Boolean, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class WhatsAppFestival(IdMixin, Base):
    """A festival FlowQR staff keep on a dated list (name, date, region). Global data. Greetings for it go only to businesses that opted in to it, and only to customers who agreed to occasion greetings.
    A row is never deleted; staff can switch one off."""

    __tablename__ = "whatsapp_festivals"
    __table_args__ = (UniqueConstraint("name", "festival_date", "region", name="uq_wa_festival"),)

    name: Mapped[str] = mapped_column(String(60))
    festival_date: Mapped[date] = mapped_column(Date)
    region: Mapped[str] = mapped_column(String(40), default="All India")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WhatsAppFestivalOptin(IdMixin, TimestampMixin, Base):
    """A business's choice to send greetings for one festival. Off unless the business turned it on."""

    __tablename__ = "whatsapp_festival_optins"
    __table_args__ = (UniqueConstraint("tenant_id", "festival_id", name="uq_wa_festival_optin"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    festival_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("whatsapp_festivals.id", ondelete="CASCADE"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class WhatsAppLink(IdMixin, Base):
    """A tracked review link: a long random token that always leads to ONE fixed destination chosen when the link was made (the business's own review page). Nothing in a request can change where it
    goes. It belongs to the business and dies only with it: deleting the message or the customer it was sent to does not break the link for whoever still holds it."""

    __tablename__ = "whatsapp_links"
    __table_args__ = (UniqueConstraint("token", name="uq_wa_link_token"), UniqueConstraint("tenant_id", "idem_key", name="uq_wa_link_idem"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    token: Mapped[str] = mapped_column(String(64))
    destination: Mapped[str] = mapped_column(String(500))
    idem_key: Mapped[str | None] = mapped_column(String(200))  # one link per send: a retry reuses it
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("whatsapp_messages.id", ondelete="SET NULL"))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("whatsapp_contacts.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WhatsAppLinkClick(IdMixin, Base):
    """One counted click: which link, which customer and message, and when. Nothing else: no address, no browser, no place. Deleted with the customer, and with the business."""

    __tablename__ = "whatsapp_link_clicks"
    __table_args__ = (Index("ix_wa_click_link_time", "link_id", "clicked_at"), Index("ix_wa_click_tenant_time", "tenant_id", "clicked_at"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    link_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("whatsapp_links.id", ondelete="CASCADE"))
    contact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("whatsapp_contacts.id", ondelete="CASCADE"))
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("whatsapp_messages.id", ondelete="SET NULL"))
    clicked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---- two-way conversations (Phase 7). A customer's messages are kept as text for a retention period the business chooses (30 to 365 days, default 90), then purged.
CONVERSATION_STATUSES = ("open", "needs_human", "closed")
SENDER_TYPES = ("customer", "ai", "staff", "system")
CONVERSATION_MESSAGE_STATUSES = ("received", "queued", "sent", "delivered", "read", "failed")


class WhatsAppConversationSettings(IdMixin, TimestampMixin, Base):
    """One row per business. Off until the owner turns the inbox on."""

    __tablename__ = "whatsapp_conversation_settings"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_wa_conv_settings_tenant"), CheckConstraint("retention_days BETWEEN 30 AND 365", name="ck_wa_conv_retention"),
                      CheckConstraint("takeover_minutes BETWEEN 5 AND 1440", name="ck_wa_conv_takeover"), CheckConstraint("debounce_seconds BETWEEN 2 AND 10", name="ck_wa_conv_debounce"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    retention_days: Mapped[int] = mapped_column(Integer, default=90)  # how long message text is kept
    takeover_minutes: Mapped[int] = mapped_column(Integer, default=60)  # how long the assistant stays quiet after a person replies or takes over
    debounce_seconds: Mapped[int] = mapped_column(Integer, default=4)  # how long to wait for more messages from the same customer before anyone answers
    notify_email: Mapped[bool] = mapped_column(Boolean, default=True)  # email the owner and admins when a conversation needs a person


class WhatsAppConversation(IdMixin, TimestampMixin, Base):
    """One conversation per customer. The 24-hour customer-service window is measured from `last_customer_message_at`."""

    __tablename__ = "whatsapp_conversations"
    __table_args__ = (UniqueConstraint("tenant_id", "contact_id", name="uq_wa_conv_contact"), UniqueConstraint("tenant_id", "code", name="uq_wa_conv_code"),
                      CheckConstraint(_in("status", CONVERSATION_STATUSES), name="ck_wa_conv_status"), Index("ix_wa_conv_tenant_last", "tenant_id", "last_message_at"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("whatsapp_contacts.id", ondelete="CASCADE"))
    code: Mapped[str] = mapped_column(String(12))  # a private nickname for this conversation: the only name an AI provider ever sees, never the customer's name or number
    status: Mapped[str] = mapped_column(String(12), default="open")
    last_customer_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_outbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unread_count: Mapped[int] = mapped_column(Integer, default=0)
    awaiting_reply: Mapped[bool] = mapped_column(Boolean, default=False)  # the customer's latest message has not been answered by anyone (kept as a flag: Meta's times are whole seconds, so times cannot order a reply against a message)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    handoff_reason: Mapped[str | None] = mapped_column(String(40))
    handoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ai_paused_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # set when a person replies or takes over
    reply_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # when the wait for more messages ends and something should happen
    last_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(16), default="organic")
    ai_off: Mapped[bool] = mapped_column(Boolean, default=False)  # the owner paused the assistant for this one conversation
    ai_disclosed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # the "automated assistant" line was sent
    holding_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # the "someone will reply" line was sent
    ai_pseudonym: Mapped[str | None] = mapped_column(String(16))  # the only name for this customer the AI provider ever sees
    booking_consent_ask_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # the booking whose "would you like reminders? Reply YES" question is waiting for an answer
    booking_consent_asked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WhatsAppConversationMessage(IdMixin, Base):
    """One message in a conversation, with who sent it. Outbound free-form messages also have a row in the message ledger (whatsapp_messages) for cost and delivery."""

    __tablename__ = "whatsapp_conversation_messages"
    __table_args__ = (CheckConstraint(_in("direction", MESSAGE_DIRECTIONS), name="ck_wa_convmsg_direction"), CheckConstraint(_in("sender_type", SENDER_TYPES), name="ck_wa_convmsg_sender"),
                      CheckConstraint(_in("delivery_status", CONVERSATION_MESSAGE_STATUSES), name="ck_wa_convmsg_status"), Index("ix_wa_convmsg_conv_created", "conversation_id", "created_at"),
                      Index("uq_wa_convmsg_meta", "tenant_id", "meta_message_id", unique=True, postgresql_where=text("meta_message_id IS NOT NULL")))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("whatsapp_conversations.id", ondelete="CASCADE"))
    direction: Mapped[str] = mapped_column(String(8))
    sender_type: Mapped[str] = mapped_column(String(10))
    staff_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    text: Mapped[str | None] = mapped_column(String(4096))  # None for a picture, a voice note or anything that is not text
    msg_type: Mapped[str] = mapped_column(String(16), default="text")
    meta_message_id: Mapped[str | None] = mapped_column(String(120))
    ledger_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("whatsapp_messages.id", ondelete="SET NULL"))
    delivery_status: Mapped[str] = mapped_column(String(10), default="received")
    error_code: Mapped[str | None] = mapped_column(String(20))
    template_key: Mapped[str | None] = mapped_column(String(40))  # set when the message was an approved template (the fallback outside the 24-hour window)
    marketing_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)  # a person saw the offer warning and confirmed (logged)
    via_app: Mapped[bool] = mapped_column(Boolean, default=False)  # typed in the WhatsApp Business app on the owner's phone (reported back by Meta)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ---- Phase 8: the AI assistant
KNOWLEDGE_KINDS = ("about", "address", "hours", "service", "faq", "policy", "booking_rule")  # no "offer": the assistant never sees offers
AI_OUTCOMES = ("replied", "handoff", "refused", "holding", "blocked", "error")


class WhatsAppAiQuota(IdMixin, Base):
    """DATED, append-only: replies a month a WhatsApp tier includes. A change is a new row with a new date (never an edit), so past months can be explained."""

    __tablename__ = "whatsapp_ai_quotas"
    __table_args__ = (UniqueConstraint("addon_key", "effective_from", name="uq_wa_ai_quota"), CheckConstraint("monthly_replies >= 0", name="ck_wa_ai_quota_nonneg"), CheckConstraint(_in("addon_key", ADDON_KEYS), name="ck_wa_ai_quota_key"))

    addon_key: Mapped[str] = mapped_column(String(24))
    monthly_replies: Mapped[int] = mapped_column(Integer)
    effective_from: Mapped[date] = mapped_column(Date)
    note: Mapped[str] = mapped_column(String(300))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WhatsAppAiSettings(IdMixin, TimestampMixin, Base):
    __tablename__ = "whatsapp_ai_settings"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_wa_ai_settings_tenant"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    privacy_ack_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # the owner's acknowledgement that customer messages go to an AI provider
    privacy_ack_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    tone: Mapped[str | None] = mapped_column(String(120))
    quota_warned_month: Mapped[str | None] = mapped_column(String(7))  # "2026-11": the 80% warning went out this month


class WhatsAppKnowledgeItem(IdMixin, TimestampMixin, Base):
    """One thing the owner tells the assistant. The only source of what it may say about the business."""

    __tablename__ = "whatsapp_knowledge_items"
    __table_args__ = (CheckConstraint(_in("kind", KNOWLEDGE_KINDS), name="ck_wa_knowledge_kind"), CheckConstraint("price_inr IS NULL OR price_inr >= 0", name="ck_wa_knowledge_price"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(14))
    title: Mapped[str | None] = mapped_column(String(120))
    body: Mapped[str] = mapped_column(String(1200))
    price_inr: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    position: Mapped[int] = mapped_column(Integer, default=0)


class WhatsAppAiRun(IdMixin, Base):
    """One assistant attempt. Tokens and latency are recorded so the monthly quota can be priced from real data. Holds no phone number and no message text."""

    __tablename__ = "whatsapp_ai_runs"
    __table_args__ = (CheckConstraint(_in("outcome", AI_OUTCOMES), name="ck_wa_ai_run_outcome"), CheckConstraint("feedback IS NULL OR feedback in ('up', 'down')", name="ck_wa_ai_run_feedback"),
                      Index("ix_wa_ai_run_tenant_created", "tenant_id", "created_at"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("whatsapp_conversations.id", ondelete="SET NULL"))
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("whatsapp_conversation_messages.id", ondelete="SET NULL"))
    provider: Mapped[str | None] = mapped_column(String(40))
    model_version: Mapped[str | None] = mapped_column(String(80))
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(10))
    handoff_reason: Mapped[str | None] = mapped_column(String(40))
    counted: Mapped[bool] = mapped_column(Boolean, default=False)  # uses one reply of the month's quota
    is_test: Mapped[bool] = mapped_column(Boolean, default=False)  # a "test it" chat run: never sent to WhatsApp, not counted
    feedback: Mapped[str | None] = mapped_column(String(4))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WhatsAppUnansweredQuestion(IdMixin, Base):
    __tablename__ = "whatsapp_unanswered_questions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("whatsapp_conversations.id", ondelete="CASCADE"))
    question: Mapped[str] = mapped_column(String(300))
    count: Mapped[int] = mapped_column(Integer, default=1)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_asked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# ---- Phase 9: appointment booking
BOOKING_STATUSES = ("booked", "done", "no_show", "cancelled")
BOOKING_SOURCES = ("ai", "staff", "api")


class WhatsAppBookingSettings(IdMixin, TimestampMixin, Base):
    __tablename__ = "whatsapp_booking_settings"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_wa_booking_settings_tenant"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    capacity: Mapped[int] = mapped_column(Integer, default=1)  # how many bookings may overlap (chairs, rooms, practitioners)
    slot_step_minutes: Mapped[int] = mapped_column(Integer, default=30)
    min_notice_minutes: Mapped[int] = mapped_column(Integer, default=60)
    max_days_ahead: Mapped[int] = mapped_column(Integer, default=30)
    reminders_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_day_hour: Mapped[int] = mapped_column(Integer, default=10)  # India time: the day-before reminder goes out at this hour
    reminder_soon_hours: Mapped[int] = mapped_column(Integer, default=2)  # the second reminder goes out this long before


class WhatsAppBookingService(IdMixin, TimestampMixin, Base):
    __tablename__ = "whatsapp_booking_services"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=0)  # kept free after each booking
    price_inr: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class WhatsAppBookingHours(IdMixin, Base):
    __tablename__ = "whatsapp_booking_hours"
    __table_args__ = (UniqueConstraint("tenant_id", "weekday", name="uq_wa_booking_hours_day"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    weekday: Mapped[int] = mapped_column(SmallInteger)  # 0 = Monday
    opens: Mapped[time] = mapped_column(Time)
    closes: Mapped[time] = mapped_column(Time)


class WhatsAppBookingClosed(IdMixin, Base):
    __tablename__ = "whatsapp_booking_closed"
    __table_args__ = (UniqueConstraint("tenant_id", "day", name="uq_wa_booking_closed_day"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date)
    reason: Mapped[str | None] = mapped_column(String(120))


class WhatsAppBooking(IdMixin, TimestampMixin, Base):
    __tablename__ = "whatsapp_bookings"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_wa_booking_code"), CheckConstraint(_in("status", BOOKING_STATUSES), name="ck_wa_booking_status"),
                      CheckConstraint(_in("source", BOOKING_SOURCES), name="ck_wa_booking_source"), Index("ix_wa_booking_tenant_start", "tenant_id", "starts_at"),
                      Index("uq_wa_booking_idem", "tenant_id", "idem_key", unique=True, postgresql_where=text("idem_key IS NOT NULL")))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    contact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("whatsapp_contacts.id", ondelete="CASCADE"), index=True)
    service_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("whatsapp_booking_services.id", ondelete="SET NULL"))
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("whatsapp_conversations.id", ondelete="SET NULL"))
    code: Mapped[str] = mapped_column(String(10))
    service_name: Mapped[str] = mapped_column(String(120))  # a copy, so renaming or removing a service never rewrites history
    duration_minutes: Mapped[int] = mapped_column(Integer)
    price_inr: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    blocks_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # ends_at plus the service's buffer: the time this booking keeps its place taken
    status: Mapped[str] = mapped_column(String(10), default="booked")
    source: Mapped[str] = mapped_column(String(10))
    note: Mapped[str | None] = mapped_column(String(300))
    idem_key: Mapped[str | None] = mapped_column(String(120))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_reason: Mapped[str | None] = mapped_column(String(120))
    reminder_day_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_day_result: Mapped[str | None] = mapped_column(String(40))
    reminder_soon_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminder_soon_result: Mapped[str | None] = mapped_column(String(40))
