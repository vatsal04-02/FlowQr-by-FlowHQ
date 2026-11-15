"""Demo requests from the public marketing site. Not tenant data: a lead exists before any business account does."""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin


class Lead(IdMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (Index("ix_leads_created", "created_at"),)

    name: Mapped[str] = mapped_column(String(120))
    business_name: Mapped[str] = mapped_column(String(160))
    city: Mapped[str] = mapped_column(String(80))
    business_type: Mapped[str] = mapped_column(String(40))
    locations: Mapped[int] = mapped_column(SmallInteger)
    phone: Mapped[str] = mapped_column(String(16))  # E.164, +91 numbers only
    whatsapp_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    preferred_time: Mapped[str | None] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(40), default="demo")
    ip_hash: Mapped[str | None] = mapped_column(String(64))  # for abuse checks only; never the raw address
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
