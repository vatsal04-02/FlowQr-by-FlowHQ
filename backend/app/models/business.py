"""Locations, Google connections, reviews, reply drafts/logs."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, SmallInteger, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin


class Location(IdMixin, TimestampMixin, Base):
    __tablename__ = "locations"
    __table_args__ = (Index("ix_locations_tenant", "tenant_id"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    address_line: Mapped[str | None] = mapped_column(String(300))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(100))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    phone: Mapped[str | None] = mapped_column(String(32))
    # The Google review URL the public landing page sends customers to. Editable without
    # touching the physical QR/NFC card.
    review_url: Mapped[str | None] = mapped_column(String(1000))
    review_url_source: Mapped[str] = mapped_column(String(16), default="manual")  # manual | google
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class GoogleConnectionStatus(str, enum.Enum):
    pending_selection = "pending_selection"
    active = "active"
    revoked = "revoked"
    error = "error"
    disconnected = "disconnected"


class GoogleConnection(IdMixin, TimestampMixin, Base):
    __tablename__ = "google_connections"
    __table_args__ = (Index("ix_gconn_tenant", "tenant_id"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    google_email: Mapped[str | None] = mapped_column(String(254))
    google_sub: Mapped[str | None] = mapped_column(String(64))
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scopes: Mapped[str | None] = mapped_column(Text)
    status: Mapped[GoogleConnectionStatus] = mapped_column(
        Enum(GoogleConnectionStatus, name="google_connection_status"), default=GoogleConnectionStatus.pending_selection
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    connected_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Whether Google has granted the FlowHQ Cloud project Business Profile API access: unknown | approved | awaiting_approval.
    # OAuth login succeeding says nothing about this; it is learned from real API responses.
    api_access: Mapped[str] = mapped_column(String(24), default="unknown", server_default="unknown")
    api_access_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Whose Google login acts on this client's profile: the client's own OAuth token (today's behaviour) or a FlowQR agency account that the client invited as MANAGER
    # (docs/audits/GOOGLE_CLIENT_ACCOUNT_OPTIONS.md, Option B). Nothing sets agency_account unless GOOGLE_AGENCY_MANAGER_ENABLED is on.
    auth_mode: Mapped[str] = mapped_column(String(16), default="client_token", server_default="client_token")  # client_token | agency_account
    agency_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("google_agency_accounts.id", ondelete="RESTRICT"))
    agency_switched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    google_locations: Mapped[list["GoogleLocation"]] = relationship(back_populates="connection")


class GoogleLocation(IdMixin, TimestampMixin, Base):
    """A Business Profile location discovered via a connection, optionally mapped to a FlowQR Location."""

    __tablename__ = "google_locations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "google_location_name", name="uq_glocation_tenant_name"),
        Index("ix_glocation_tenant", "tenant_id"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("google_connections.id", ondelete="CASCADE"))
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    google_account_name: Mapped[str] = mapped_column(String(120))  # accounts/123
    google_location_name: Mapped[str] = mapped_column(String(120))  # locations/456
    title: Mapped[str | None] = mapped_column(String(300))
    address: Mapped[str | None] = mapped_column(String(500))
    place_id: Mapped[str | None] = mapped_column(String(200))
    lat: Mapped[float | None] = mapped_column(Float)  # cached from Places once (centre of the local-rank search)
    lng: Mapped[float | None] = mapped_column(Float)
    review_url: Mapped[str | None] = mapped_column(String(1000))
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str | None] = mapped_column(String(24))  # ok | error | rate_limited | running
    last_sync_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    next_sync_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_google_account_name: Mapped[str | None] = mapped_column(String(120))  # the account the client's own login saw, kept when an agency switch re-points google_account_name

    connection: Mapped[GoogleConnection] = relationship(back_populates="google_locations")


class GoogleAgencyAccount(IdMixin, TimestampMixin, Base):
    """A FlowQR agency Google login. PLATFORM-ONLY (row-level security admits the bypass context only); tokens are encrypted with AGENCY_TOKEN_ENCRYPTION_KEY, never the client-token key.
    Read and refreshed only through services/google/agency.py. Several may exist; a connection records which one it uses."""

    __tablename__ = "google_agency_accounts"

    label: Mapped[str] = mapped_column(String(80), unique=True)
    google_email: Mapped[str] = mapped_column(String(254), unique=True)
    google_sub: Mapped[str | None] = mapped_column(String(64))
    refresh_token_encrypted: Mapped[str | None] = mapped_column(Text)
    access_token_encrypted: Mapped[str | None] = mapped_column(Text)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(12), default="active", server_default="active")  # active | disabled | revoked
    max_locations: Mapped[int | None] = mapped_column(Integer)  # NULL = no cap recorded: Google's limit for one account is NOT verified
    location_group_name: Mapped[str | None] = mapped_column(String(120))  # the FlowQR LocationGroup this login belongs to (accounts/<id>); NULL = can only be invited as an individual
    last_error: Mapped[str | None] = mapped_column(String(300))


class GoogleAgencyAuthorization(IdMixin, TimestampMixin, Base):
    """One client location and the story of FlowQR becoming, and stopping being, its manager: the stored consent, invite, acceptance, the separate notice, removal.
    Holds no Google content and no token."""

    __tablename__ = "google_agency_authorizations"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("google_connections.id", ondelete="CASCADE"))
    google_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("google_locations.id", ondelete="CASCADE"))
    agency_account_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("google_agency_accounts.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(16), default="consented", server_default="consented")
    consent_version: Mapped[str] = mapped_column(String(40))
    consent_text_sha256: Mapped[str] = mapped_column(String(64))
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consented_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    consented_by_email: Mapped[str | None] = mapped_column(String(254))  # snapshot: the evidence survives the user's deletion; also where the notice goes
    admin_resource_name: Mapped[str | None] = mapped_column(String(200))  # locations/{id}/admins/{admin}: what removal needs
    invitation_name: Mapped[str | None] = mapped_column(String(200))
    target_type: Mapped[str] = mapped_column(String(24), default="individual_agency_user", server_default="individual_agency_user")  # individual_agency_user | flowhq_location_group
    target_account_name: Mapped[str | None] = mapped_column(String(120))  # the LocationGroup that was invited (accounts/<id>); only for a group target
    google_location_resource: Mapped[str | None] = mapped_column(String(120))  # `locations/<id>`: the SAME for every business, so ONE open authorization per Google location can be enforced platform-wide
    invite_scope: Mapped[str] = mapped_column(String(16), default="location", server_default="location")  # what the client chose: location | business_group
    consent_request_id: Mapped[str | None] = mapped_column(String(64))  # replay protection: the client's request id for this consent
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # when Google was last asked about this invitation
    receiving_account_name: Mapped[str | None] = mapped_column(String(120))  # the account whose invitation list the pending invitation was FOUND under (read from Google)
    agency_account_name: Mapped[str | None] = mapped_column(String(120))  # accounts/{a}: where the AGENCY login sees this location (read after acceptance, never assumed)
    invite_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    switched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_token_revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    client_token_revoke_attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    notice_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notice_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notice_overdue_alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removal_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removal_requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    removal_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removal_alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lost_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(40))
    last_error: Mapped[str | None] = mapped_column(String(300))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReplyStatus(str, enum.Enum):
    draft = "draft"
    approved = "approved"
    publishing = "publishing"  # sent to Google, waiting for Google's answer (committed before the call so it is visible)
    published = "published"
    failed = "failed"
    rejected = "rejected"


class Review(IdMixin, TimestampMixin, Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("google_location_id", "external_id", name="uq_review_glocation_external"),
        Index("ix_reviews_tenant_loc_created", "tenant_id", "location_id", "review_created_at"),
        Index("ix_reviews_tenant_rating", "tenant_id", "rating"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    location_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("locations.id", ondelete="SET NULL"))
    google_location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("google_locations.id", ondelete="CASCADE"))
    external_id: Mapped[str] = mapped_column(String(200))  # Google review resource id
    rating: Mapped[int] = mapped_column(SmallInteger)
    text: Mapped[str | None] = mapped_column(Text)
    reviewer_name: Mapped[str | None] = mapped_column(String(200))
    review_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    review_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    update_count: Mapped[int] = mapped_column(Integer, default=0)
    # Reply state as reported by Google (only set after Google confirms).
    google_reply_text: Mapped[str | None] = mapped_column(Text)
    google_reply_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Google's moderation of the owner reply: PENDING | APPROVED | REJECTED (NULL when Google did not report one).
    # A REJECTED reply is not public, so google_reply_text stays NULL for it.
    google_reply_state: Mapped[str | None] = mapped_column(String(16))
    google_reply_policy_violation: Mapped[str | None] = mapped_column(String(64))

    drafts: Mapped[list["ReplyDraft"]] = relationship(back_populates="review", order_by="ReplyDraft.created_at")

    @property
    def has_google_reply(self) -> bool:
        return self.google_reply_text is not None


class ReplyDraft(IdMixin, TimestampMixin, Base):
    __tablename__ = "reply_drafts"
    __table_args__ = (Index("ix_reply_drafts_tenant_status", "tenant_id", "status"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    review_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[ReplyStatus] = mapped_column(Enum(ReplyStatus, name="reply_status"), default=ReplyStatus.draft)
    language: Mapped[str] = mapped_column(String(16), default="en")
    generated_by_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    requires_human_handling: Mapped[bool] = mapped_column(Boolean, default=False)
    flag_reasons: Mapped[list] = mapped_column(JSONB, default=list)
    risk_level: Mapped[str | None] = mapped_column(String(8))  # low | medium | high (services/ai/safety.assess_risk)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    auto_published: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")  # approved by the template rule (services/auto_reply.py), not by a person
    template_index: Mapped[int | None] = mapped_column(SmallInteger)  # which template an automatic reply used (rotation)

    review: Mapped[Review] = relationship(back_populates="drafts")


class ReplyLog(IdMixin, Base):
    """Append-only record of each publish attempt against Google."""

    __tablename__ = "reply_logs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    review_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True)
    draft_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reply_drafts.id", ondelete="SET NULL"))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(32))  # publish_attempt
    success: Mapped[bool] = mapped_column(Boolean)
    http_status: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
