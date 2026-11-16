"""Local rank tracking: keywords a business wants to watch for one Google location, and each measurement (tenant-scoped, RLS).

A RankCheck is only written from a real answer by the places provider (or its error). Nothing here is estimated."""
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin, utcnow


class RankKeyword(IdMixin, TimestampMixin, Base):
    __tablename__ = "rank_keywords"
    __table_args__ = (UniqueConstraint("google_location_id", "keyword", name="uq_rank_keyword_location"), Index("ix_rank_keywords_tenant", "tenant_id"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    google_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("google_locations.id", ondelete="CASCADE"))
    keyword: Mapped[str] = mapped_column(String(80))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class RankCheck(IdMixin, Base):
    __tablename__ = "rank_checks"
    __table_args__ = (CheckConstraint("status in ('ok','error')", name="ck_rank_check_status"),
                      Index("ix_rank_checks_keyword", "keyword_id", "checked_at"), Index("ix_rank_checks_tenant_month", "tenant_id", "checked_at"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    keyword_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rank_keywords.id", ondelete="CASCADE"))
    google_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("google_locations.id", ondelete="CASCADE"))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(12))
    rank: Mapped[int | None] = mapped_column(SmallInteger)
    results_seen: Mapped[int | None] = mapped_column(SmallInteger)
    top_results: Mapped[list] = mapped_column(JSONB, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(8), default="manual")
    center_lat: Mapped[float | None] = mapped_column(Float)
    center_lng: Mapped[float | None] = mapped_column(Float)
