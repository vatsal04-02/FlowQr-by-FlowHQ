"""Pinned competitors (Competitor Analysis, stage 2) and the dated observations kept for them (tenant-scoped, RLS).

A snapshot is only ever written from a real Google Places result that FlowQR already received for one of the business's own rank checks (source "rank_check"): the rating and review
count Google returned for that place on that date, and the position the place held in that search. Pinning never triggers a Google call, and nothing between observations is estimated."""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin, utcnow

PIN_LIMIT_PER_LOCATION = 5


class PinnedCompetitor(IdMixin, TimestampMixin, Base):
    __tablename__ = "pinned_competitors"
    __table_args__ = (UniqueConstraint("google_location_id", "place_id", name="uq_pinned_competitor"), Index("ix_pinned_competitors_tenant", "tenant_id"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    google_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("google_locations.id", ondelete="CASCADE"))
    place_id: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(300))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class CompetitorSnapshot(IdMixin, Base):
    __tablename__ = "competitor_snapshots"
    __table_args__ = (
        UniqueConstraint("competitor_id", "rank_check_id", name="uq_competitor_snapshot_check"),
        CheckConstraint("source in ('rank_check')", name="ck_competitor_snapshot_source"),
        Index("ix_competitor_snapshots_competitor", "competitor_id", "observed_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    competitor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pinned_competitors.id", ondelete="CASCADE"))
    rank_check_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rank_checks.id", ondelete="CASCADE"))
    keyword_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("rank_keywords.id", ondelete="SET NULL"))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    rating: Mapped[float | None] = mapped_column(Float)
    reviews: Mapped[int | None] = mapped_column(Integer)
    position: Mapped[int | None] = mapped_column(SmallInteger)  # 1-based position in that search's first 20 results
    your_position: Mapped[int | None] = mapped_column(SmallInteger)  # where the business itself stood in the same search (None = not in the first 20)
    source: Mapped[str] = mapped_column(String(16), default="rank_check")
