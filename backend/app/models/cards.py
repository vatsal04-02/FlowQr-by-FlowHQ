"""QR/NFC cards, batches, assignment history, scan events."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin


class CardStatus(str, enum.Enum):
    unassigned = "unassigned"
    assigned = "assigned"
    active = "active"
    deactivated = "deactivated"
    lost = "lost"


class CardBatch(IdMixin, TimestampMixin, Base):
    __tablename__ = "card_batches"

    name: Mapped[str] = mapped_column(String(200))
    prefix: Mapped[str] = mapped_column(String(8), default="FQR")
    quantity: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)
    base_url: Mapped[str | None] = mapped_column(String(300))  # PUBLIC_CARD_BASE_URL at generation time (printed on the cards)


class QRCard(IdMixin, TimestampMixin, Base):
    __tablename__ = "qr_cards"
    __table_args__ = (
        Index("ix_qr_cards_tenant", "tenant_id"),
        Index("ix_qr_cards_status", "status"),
    )

    card_code: Mapped[str] = mapped_column(String(32), unique=True)  # FQR-0001 (printed on card)
    public_token: Mapped[str] = mapped_column(String(64), unique=True)  # unguessable, permanent
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("card_batches.id", ondelete="SET NULL"), index=True)
    status: Mapped[CardStatus] = mapped_column(Enum(CardStatus, name="card_status"), default=CardStatus.unassigned)
    # NULL while unassigned. RLS: tenant sees only its own cards; platform admin bypasses.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="SET NULL"))
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    label: Mapped[str | None] = mapped_column(String(120))  # e.g. "Reception desk"
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class CardAssignment(IdMixin, Base):
    """History of card ownership so reassignment never rewrites the past."""

    __tablename__ = "card_assignments"

    card_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("qr_cards.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ScanEventType(str, enum.Enum):
    scan = "scan"  # token resolved by backend (QR scan or NFC tap)
    landing_view = "landing_view"  # landing page actually rendered in a browser
    ai_assist = "ai_assist"  # customer used the writing assistant
    copy = "copy"
    google_click = "google_click"  # clicked "Continue to Google" (NOT proof a review was posted)
    fallback = "fallback"  # inactive/unassigned/unknown card scanned


class ScanEvent(IdMixin, Base):
    __tablename__ = "scan_events"
    __table_args__ = (
        Index("ix_scan_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_scan_events_card_created", "card_id", "created_at"),
        Index("ix_scan_events_type_created", "event_type", "created_at"),
    )

    card_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("qr_cards.id", ondelete="SET NULL"))
    # Snapshot of ownership at event time: survives card reassignment.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="SET NULL"))
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    event_type: Mapped[ScanEventType] = mapped_column(Enum(ScanEventType, name="scan_event_type"))
    visitor_hash: Mapped[str | None] = mapped_column(String(64))  # salted daily hash of ip+ua, not reversible
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
