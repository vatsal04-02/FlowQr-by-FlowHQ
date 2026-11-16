"""Review Growth: self-serve QR campaigns, anonymous customer review sessions, AI drafts and funnel events.

Privacy: no customer name, phone or email is ever stored. `customer_input` (free text the customer typed) and the
drafts are deleted after `review_session_retention_days`; `review_events` carry no text and are kept for analytics.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin

CAMPAIGN_STATUSES = ("active", "paused", "archived")
EVENT_TYPES = (
    "scan", "feedback_submitted", "suggestion_selected", "ai_requested", "manual_selected", "needs_more", "draft_generated", "draft_regenerated",
    "generation_failed", "draft_approved", "review_copied", "google_redirect", "review_submitted", "review_submit_failed",
)


class ReviewCampaign(IdMixin, TimestampMixin, Base):
    __tablename__ = "review_campaigns"
    __table_args__ = (
        Index("ix_review_campaigns_tenant", "tenant_id", "status"),
        CheckConstraint("status in ('active','paused','archived')", name="ck_review_campaign_status"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    # SET NULL: a deleted location must not delete the campaign's analytics; the public page then reports "inactive".
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(120))
    public_id: Mapped[str] = mapped_column(String(32), unique=True)  # what the QR encodes; random, never the row id
    status: Mapped[str] = mapped_column(String(12), default="active")
    customization: Mapped[dict] = mapped_column(JSONB, default=dict)
    qr_style: Mapped[dict | None] = mapped_column(JSONB)  # how this campaign's code is drawn; NULL = the business's style
    qr_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class ReviewSession(IdMixin, Base):
    """One anonymous customer visit that submitted feedback. Deleted after the retention period."""

    __tablename__ = "review_sessions"
    __table_args__ = (
        Index("ix_review_sessions_campaign_created", "campaign_id", "created_at"),
        Index("ix_review_sessions_created", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("review_campaigns.id", ondelete="CASCADE"))
    session_identifier: Mapped[str] = mapped_column(String(32), unique=True)  # held by the customer's browser
    language: Mapped[str] = mapped_column(String(8), default="en")
    style: Mapped[str] = mapped_column(String(16), default="natural")
    customer_input: Mapped[dict] = mapped_column(JSONB, default=dict)  # {service, appreciated, details}
    rating: Mapped[int | None] = mapped_column(SmallInteger)  # optional; never used to route or filter the customer
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ReviewDraft(IdMixin, TimestampMixin, Base):
    __tablename__ = "review_drafts"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("review_sessions.id", ondelete="CASCADE"), unique=True)
    generated_content: Mapped[str | None] = mapped_column(Text)  # latest AI draft (NULL if AI was unavailable)
    final_content: Mapped[str | None] = mapped_column(Text)  # the customer's own approved/edited text
    generation_count: Mapped[int] = mapped_column(Integer, default=0)
    ai_assisted: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReviewEvent(IdMixin, Base):
    """Funnel event. Holds no customer text; survives the session purge (session_id becomes NULL)."""

    __tablename__ = "review_events"
    __table_args__ = (
        Index("ix_review_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_review_events_campaign_type_created", "campaign_id", "event_type", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("review_campaigns.id", ondelete="CASCADE"))
    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("review_sessions.id", ondelete="SET NULL"))
    # Snapshot of where the campaign pointed when this happened: survives re-pointing the campaign to another location.
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    event_type: Mapped[str] = mapped_column(String(24))
    suggestion_id: Mapped[str | None] = mapped_column(String(40))  # catalog topic id, only on "suggestion_selected" events
    rating: Mapped[int | None] = mapped_column(SmallInteger)  # the 1-5 stars the customer chose on the FlowQR page (not a Google rating); only on "feedback_submitted"
    visitor_hash: Mapped[str | None] = mapped_column(String(64))  # salted daily hash of ip+ua, not reversible
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RetiredCampaignId(IdMixin, Base):
    """An EARLIER public id of a campaign (the table name is historical). It keeps resolving to the campaign, so copies
    printed before a new code was issued stay usable, unless the business deliberately deactivated it (`deactivated_at`).
    Ids listed here are never issued again."""

    __tablename__ = "review_campaign_retired_ids"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    campaign_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("review_campaigns.id", ondelete="CASCADE"), index=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True)
    retired_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    retired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # when a newer code was issued
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # NULL = still works


class ReviewRequestTemplate(IdMixin, TimestampMixin, Base):
    """A reusable, neutral message asking a customer for a review (WhatsApp, SMS, email or a printed line). Neutral by rule: the same
    words for every customer, no incentive, no rating mentioned, no "only if you were happy" (checked on save)."""
    __tablename__ = "review_request_templates"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    channel: Mapped[str] = mapped_column(String(16), default="whatsapp")  # whatsapp | sms | email | print
    language: Mapped[str] = mapped_column(String(8), default="en")
    body: Mapped[str] = mapped_column(Text)  # may contain {customer}, {business}, {link}
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

