"""Google Marketing Studio: campaigns and the media/document library.

A campaign is a plan (brief, objective, length). Its posts are ordinary `scheduled_posts` rows (campaign_id set), so approval, scheduling, retries, the
governed publisher and read-back all stay in ONE place. Nothing here talks to Google.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, LargeBinary, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin

OBJECTIVES = ("keep_active", "products", "offers", "enquiries", "events", "awareness")
DURATIONS = (7, 15, 30)
ASSET_KINDS = ("image", "document")


class MarketingCampaign(IdMixin, TimestampMixin, Base):
    __tablename__ = "marketing_campaigns"
    __table_args__ = (
        CheckConstraint("objective in ('keep_active','products','offers','enquiries','events','awareness')", name="ck_marketing_campaign_objective"),
        CheckConstraint("duration_days in (7,15,30)", name="ck_marketing_campaign_duration"),
        CheckConstraint("status in ('generating','ready','failed','archived')", name="ck_marketing_campaign_status"),
        Index("ix_marketing_campaigns_tenant", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    google_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("google_locations.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(120))
    brief: Mapped[str] = mapped_column(Text)
    objective: Mapped[str] = mapped_column(String(16))
    duration_days: Mapped[int] = mapped_column(SmallInteger)
    start_date: Mapped[date] = mapped_column(Date)
    language: Mapped[str] = mapped_column(String(8), default="en")
    status: Mapped[str] = mapped_column(String(16), default="generating")
    # Owner-given facts for an events campaign (the AI never invents an event).
    event_title: Mapped[str | None] = mapped_column(String(58))
    event_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    asset_ids: Mapped[list] = mapped_column(JSONB, default=list)  # library items the owner chose as context for this campaign
    notes: Mapped[list] = mapped_column(JSONB, default=list)  # plain-language things the owner should know (a skipped offer, a missing fact)
    keywords: Mapped[list] = mapped_column(JSONB, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class MarketingAsset(IdMixin, TimestampMixin, Base):
    """An uploaded image or document, owned by one business. Documents never leave FlowQR. An image gets a random `public_token` ONLY when it is attached to a
    post, because Google fetches post photos from a public URL (sourceUrl is the only field the Posts API accepts)."""
    __tablename__ = "marketing_assets"
    __table_args__ = (
        CheckConstraint("kind in ('image','document')", name="ck_marketing_asset_kind"),
        Index("ix_marketing_assets_tenant", "tenant_id", "created_at"),
        Index("ix_marketing_assets_token", "public_token", unique=True),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(10))
    file_name: Mapped[str | None] = mapped_column(String(200))
    label: Mapped[str | None] = mapped_column(String(200))
    content_type: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    text_excerpt: Mapped[str | None] = mapped_column(Text)  # what could be read from a document (never from an image); used only as campaign context
    public_token: Mapped[str | None] = mapped_column(String(48))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
