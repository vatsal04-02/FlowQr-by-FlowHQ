"""Google Business Profile daily metrics, as Google reported them (tenant-scoped, RLS).

One row per location, metric and calendar day. A row is only ever written from a successful Performance API response (see services/gbp_metrics.py): there is no backfill,
no estimate and nothing is derived from the latest-only GbpSnapshot summary. `fetched_at` is when FlowQR last received that day's value (Google revises recent days, so
a later fetch may update it); `first_fetched_at` is when FlowQR first saw it. `source` names the API so a second provider can never be mistaken for Google."""
import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, CheckConstraint, Date, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, utcnow

SOURCE_PERFORMANCE_API = "gbp_performance_api"


class GbpMetricDaily(IdMixin, Base):
    __tablename__ = "gbp_metric_daily"
    __table_args__ = (
        UniqueConstraint("google_location_id", "metric", "day", name="uq_gbp_metric_daily"),
        CheckConstraint("value >= 0", name="ck_gbp_metric_value"),
        Index("ix_gbp_metric_tenant_day", "tenant_id", "day"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    google_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("google_locations.id", ondelete="CASCADE"))
    metric: Mapped[str] = mapped_column(String(48))  # a DailyMetric name such as CALL_CLICKS
    day: Mapped[date] = mapped_column(Date)
    value: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(40), default=SOURCE_PERFORMANCE_API)
    first_fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
