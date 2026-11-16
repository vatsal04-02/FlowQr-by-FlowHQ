import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin


class NotificationPref(IdMixin, TimestampMixin, Base):
    """One person's notification choices in one business (PRD §5.4 / §9): which events reach them by email, and when they last opened the
    bell. Missing row = the defaults below. Tenant-scoped with the usual RLS policy."""

    __tablename__ = "notification_prefs"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_notification_prefs_member"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    email_new_review: Mapped[bool] = mapped_column(Boolean, default=False)
    email_flagged_review: Mapped[bool] = mapped_column(Boolean, default=True)
    email_sync_failed: Mapped[bool] = mapped_column(Boolean, default=True)
    email_trial_ending: Mapped[bool] = mapped_column(Boolean, default=True)
    bell_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # watermark for the hourly email job: only events after this are mailed, so nothing is sent twice
    last_emailed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


DEFAULTS = {"email_new_review": False, "email_flagged_review": True, "email_sync_failed": True, "email_trial_ending": True}
