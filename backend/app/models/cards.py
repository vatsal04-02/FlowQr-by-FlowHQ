"""QR/NFC cards, batches, assignment history, scan events."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin


class CardStatus(str, enum.Enum):
    generated = "generated"  # created in a batch, not yet marked printed / in stock
    unassigned = "unassigned"  # in stock: printed, belongs to nobody
    assigned = "assigned"
    active = "active"
    deactivated = "deactivated"
    lost = "lost"
    paused = "paused"  # temporarily off: scans show the inactive notice until the business resumes it
    reserved = "reserved"  # set aside for one business (tenant_id set, no location yet); scans still show "not set up"
    archived = "archived"  # taken out of stock lists, reversible (only while it belongs to nobody)
    retired = "retired"  # permanently out of use; the history stays, the card can never go live again


class CardBatch(IdMixin, TimestampMixin, Base):
    __tablename__ = "card_batches"

    name: Mapped[str] = mapped_column(String(200))
    prefix: Mapped[str] = mapped_column(String(8), default="FQR")
    quantity: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    notes: Mapped[str | None] = mapped_column(Text)
    base_url: Mapped[str | None] = mapped_column(String(300))  # PUBLIC_CARD_BASE_URL at generation time (printed on the cards)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # marked printed / in stock (generated -> unassigned)


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
    # The review campaign this card opens. NULL = the plain card landing page (how every card behaved before campaigns existed).
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("review_campaigns.id", ondelete="SET NULL"), index=True)
    # Which public path the PRINTED QR encodes: 'c' for cards that existed before inventory batches, 'q' for new ones.
    # The NFC address (/n/<token>) is the same for all cards. Never changed after a card exists: it is what is on paper.
    qr_path: Mapped[str] = mapped_column(String(1), default="q", server_default="c")
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    # Where a scan or tap goes INSTEAD of the card's review landing page. NULL = the landing page (how every card behaved before this existed). Set only through
    # services/destinations.py, which validates it, records the change in card_destination_history and audits it.
    destination_url: Mapped[str | None] = mapped_column(String(2000))
    destination_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # An admin's statement that the NFC tag was written with this card's NFC address. FlowQR cannot write tags: only a real NFC tap (a scan event with channel 'nfc') confirms it.
    nfc_programmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    nfc_programmed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class CardDestinationHistory(IdMixin, Base):
    """Append-only: every time a card's destination was set or cleared (old URL, new URL, who, why, when)."""

    __tablename__ = "card_destination_history"

    card_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("qr_cards.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(8))  # set | cleared
    old_url: Mapped[str | None] = mapped_column(String(2000))
    new_url: Mapped[str | None] = mapped_column(String(2000))
    reason: Mapped[str | None] = mapped_column(String(300))
    changed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CardAssignment(IdMixin, Base):
    """History of card ownership so reassignment never rewrites the past."""

    __tablename__ = "card_assignments"

    card_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("qr_cards.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    assigned_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("review_campaigns.id", ondelete="SET NULL"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_reason: Mapped[str | None] = mapped_column(String(24))  # reassigned | unassigned | retired


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
    channel: Mapped[str | None] = mapped_column(String(8))  # 'qr' | 'nfc'; NULL for events recorded before the channel was tracked
    referrer_host: Mapped[str | None] = mapped_column(String(120))  # host only (never a path or query); NULL when unknown or opened directly
    device: Mapped[str | None] = mapped_column(String(8))  # mobile | tablet | desktop | other
    placement: Mapped[str | None] = mapped_column(String(120))  # the card's label (e.g. "Reception desk") when the event happened
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("review_campaigns.id", ondelete="SET NULL"))  # the card's campaign when the event happened
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class QRStyle(IdMixin, TimestampMixin, Base):
    """A business's QR look (colours, margin, error correction, caption, logo). Purely visual: it never affects what a code
    encodes. One row per tenant; campaigns may override `style` (review_campaigns.qr_style) but share the logo."""

    __tablename__ = "qr_styles"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), unique=True)
    style: Mapped[dict] = mapped_column(JSONB, default=dict)
    logo_png: Mapped[bytes | None] = mapped_column(LargeBinary)  # validated and re-encoded on upload (services/qr_style.normalise_logo)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
