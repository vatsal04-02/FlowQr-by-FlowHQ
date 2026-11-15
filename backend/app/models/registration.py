"""Registration gate: addresses allowed to create an account in `allowlist` mode (services/registration.py). Not tenant-scoped."""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, utcnow


class RegistrationAllowlist(IdMixin, Base):
    __tablename__ = "registration_allowlist"
    __table_args__ = (UniqueConstraint("email", name="uq_registration_allowlist_email"),)

    email: Mapped[str] = mapped_column(String(320))  # normalised: NFKC, trimmed, lower case
    note: Mapped[str | None] = mapped_column(String(300))
    added_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
