"""Geo-grid ranking: a business is searched for from several points on a map, not only from its own address, because local results change from street to street.

A RankGrid is a set of coordinates around one Google location (a generated square grid, or points the owner chose). A RankGridScan is one run of one keyword over
that grid; each RankGridPoint is one real Places search from one coordinate. Nothing here is estimated: a point is either a measured rank, "not in the first 20"
(rank NULL, status ok) or an error (status error, never read as a rank). All tenant-scoped (RLS)."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, SmallInteger, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin, utcnow


class RankGrid(IdMixin, TimestampMixin, Base):
    __tablename__ = "rank_grids"
    __table_args__ = (UniqueConstraint("google_location_id", "name", name="uq_rank_grid_name"), CheckConstraint("mode in ('square','custom')", name="ck_rank_grid_mode"),
                      Index("ix_rank_grids_tenant", "tenant_id"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    google_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("google_locations.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(60))
    mode: Mapped[str] = mapped_column(String(8), default="square")
    center_lat: Mapped[float | None] = mapped_column(Float)  # NULL = the location's own position
    center_lng: Mapped[float | None] = mapped_column(Float)
    size: Mapped[int | None] = mapped_column(SmallInteger)  # square: points per side (3, 5 or 7)
    spacing_m: Mapped[int | None] = mapped_column(Integer)  # square: metres between neighbouring points
    points: Mapped[list] = mapped_column(JSONB, default=list)  # the resolved coordinates [{"i","lat","lng","label"}]: stored so history stays comparable
    points_hash: Mapped[str] = mapped_column(String(64), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class RankGridScan(IdMixin, Base):
    __tablename__ = "rank_grid_scans"
    __table_args__ = (CheckConstraint("status in ('running','done','partial','failed')", name="ck_rank_grid_scan_status"),
                      Index("ix_rank_grid_scans_grid", "grid_id", "keyword_id", "started_at"), Index("ix_rank_grid_scans_tenant", "tenant_id", "started_at"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    google_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("google_locations.id", ondelete="CASCADE"))
    grid_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rank_grids.id", ondelete="CASCADE"))
    keyword_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rank_keywords.id", ondelete="CASCADE"))
    points_hash: Mapped[str] = mapped_column(String(64))  # the coordinates this scan used: two scans compare only if these match
    source: Mapped[str] = mapped_column(String(8), default="manual")  # manual | auto
    status: Mapped[str] = mapped_column(String(8), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    points_total: Mapped[int] = mapped_column(SmallInteger, default=0)
    points_ok: Mapped[int] = mapped_column(SmallInteger, default=0)
    points_found: Mapped[int] = mapped_column(SmallInteger, default=0)  # measured points where the business is in the first 20
    arp: Mapped[float | None] = mapped_column(Float)  # average rank over measured points, "not found" counted as 21
    atrp: Mapped[float | None] = mapped_column(Float)  # average rank over the points where it was found
    solv: Mapped[float | None] = mapped_column(Float)  # % of measured points where it is in the top 3
    coverage: Mapped[float | None] = mapped_column(Float)  # % of measured points where it is in the first 20
    calls: Mapped[int] = mapped_column(SmallInteger, default=0)  # billed Places searches this scan made
    change: Mapped[dict | None] = mapped_column(JSONB)  # versus the previous comparable scan; see services/rank_grid.compare
    error: Mapped[str | None] = mapped_column(Text)


class RankGridPoint(IdMixin, Base):
    __tablename__ = "rank_grid_points"
    __table_args__ = (CheckConstraint("status in ('ok','error')", name="ck_rank_grid_point_status"), UniqueConstraint("scan_id", "point_index", name="uq_rank_grid_point"),
                      Index("ix_rank_grid_points_tenant_month", "tenant_id", "checked_at"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    scan_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rank_grid_scans.id", ondelete="CASCADE"), index=True)
    point_index: Mapped[int] = mapped_column(SmallInteger)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(8))
    rank: Mapped[int | None] = mapped_column(SmallInteger)
    results_seen: Mapped[int | None] = mapped_column(SmallInteger)
    error: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
