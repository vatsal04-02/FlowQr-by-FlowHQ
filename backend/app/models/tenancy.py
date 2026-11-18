"""Tenants, users, memberships, auth sessions, invitations, reset tokens."""
import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Integer, Boolean, DateTime, Enum, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin, utcnow


class Role(str, enum.Enum):
    owner = "owner"
    admin = "admin"
    staff = "staff"


ROLE_RANK = {Role.staff: 1, Role.admin: 2, Role.owner: 3}


class Tenant(IdMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    category: Mapped[str | None] = mapped_column(String(80))
    ai_monthly_budget_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))  # per-business monthly AI budget; NULL = the platform default
    places_monthly_cap: Mapped[int | None] = mapped_column(Integer)  # per-business ceiling on Places searches (single checks + map points); NULL = only the plan's own limits
    email: Mapped[str | None] = mapped_column(String(254))
    phone: Mapped[str | None] = mapped_column(String(32))
    address: Mapped[str | None] = mapped_column(Text)
    website: Mapped[str | None] = mapped_column(String(300))
    language: Mapped[str] = mapped_column(String(16), default="en")  # en | hi | hinglish
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Kolkata")
    logo_url: Mapped[str | None] = mapped_column(String(500))
    brand_tone: Mapped[str | None] = mapped_column(String(300))  # e.g. "warm, professional"
    ai_instructions: Mapped[str | None] = mapped_column(Text)  # business-specific reply instructions
    onboarding_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    contact_name: Mapped[str | None] = mapped_column(String(120))  # the person at the shop (optional; a contact, NOT a user account)
    origin: Mapped[str] = mapped_column(String(12), default="self_service", server_default="self_service")  # self_service | admin (created by FlowQR staff for a shop that has no login)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))  # who created the record through the admin console
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))  # who last edited it through the admin console
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspension_reason: Mapped[str | None] = mapped_column(String(300))
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # owner asked to delete the business
    deletion_scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # when the daily job will do it (cancellable until then)
    support_status: Mapped[str] = mapped_column(String(16), default="none")  # none | open | waiting | resolved
    support_note: Mapped[str | None] = mapped_column(Text)
    # Review Growth business context, owner-edited: {category_key, description, services[], disabled_suggestions[], languages[]}
    review_context: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))
    # reviews per calendar month the owner aims for (Overview "Monthly review goal"); NULL = not set, the dashboard suggests one
    review_goal: Mapped[int | None] = mapped_column(Integer)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="tenant")


class TenantAgreement(IdMixin, Base):
    """Append-only: a FLOWQR ADMINISTRATOR recorded an offline agreement on behalf of a business. It is not the shopkeeper personally accepting terms and says nothing about their age:
    `statement` carries that wording on every row so no screen or export can present it as a personal acceptance."""

    __tablename__ = "tenant_agreements"

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    terms_version: Mapped[str] = mapped_column(String(40))
    method: Mapped[str] = mapped_column(String(12))  # phone | in_person | whatsapp | paper | other
    note: Mapped[str | None] = mapped_column(String(300))
    statement: Mapped[str] = mapped_column(String(300))


class DataRequest(IdMixin, Base):
    """An administrator-handled request to EXPORT or DELETE the data of a business that has no owner login (an owner uses Settings, which is not possible here).

    Nothing is deleted or sent automatically. The request must have its requester's identity verified by an administrator first; an export is generated and handed over by an
    administrator; a deletion is executed by an administrator, typed-name confirmed, and only after a cooling-off period. `tenant_id` becomes NULL when the business is deleted and
    `business_name` is a snapshot, so the record of what was asked and done survives the deletion. Platform-only: row-level security admits the bypass context and nothing else."""

    __tablename__ = "data_requests"

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="SET NULL"), index=True)
    business_name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(10))  # export | deletion
    status: Mapped[str] = mapped_column(String(10), default="open")  # open | verified | fulfilled | rejected | cancelled
    requester_name: Mapped[str] = mapped_column(String(120))
    requester_role: Mapped[str] = mapped_column(String(14))  # owner | representative | other
    received_via: Mapped[str] = mapped_column(String(12))  # phone | in_person | whatsapp | email | paper | other
    requester_contact: Mapped[str | None] = mapped_column(String(200))  # erased when the request is resolved
    request_note: Mapped[str | None] = mapped_column(String(300))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    verification_method: Mapped[str | None] = mapped_column(String(24))
    verification_note: Mapped[str | None] = mapped_column(String(300))
    contact_matched_record: Mapped[bool | None] = mapped_column()  # the number or address used to verify was the one already on the business record
    verified_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    eligible_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # deletion only: not before this time
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[str | None] = mapped_column(String(300))
    export_count: Mapped[int] = mapped_column(Integer, default=0)  # how many times the export was generated for this request


class DataRequestEvent(IdMixin, Base):
    """Append-only history of a data request: every step, who took it, when."""

    __tablename__ = "data_request_events"

    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("data_requests.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="SET NULL"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(24))
    detail: Mapped[str | None] = mapped_column(String(300))


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(254), unique=True)  # stored lower-cased
    # NULL for accounts created through "Continue with Google" until the user sets a password.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    # Google's stable account id (the ID token `sub`). Never derived from, or matched by, email alone.
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    # The Google account photo (an https link on Google's own image host, refreshed at each Google sign-in). Never the image itself; NULL for everyone who has not signed in with Google.
    picture_url: Mapped[str | None] = mapped_column(String(500))
    phone: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # "I confirm that I am 18 years of age or older" (ticked at sign-up; no date of birth is collected). NULL for everyone who registered before the declaration existed: their status is unknown, not assumed.
    age_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    age_declaration_version: Mapped[str | None] = mapped_column(String(24))
    # Deleting one's OWN account (the business is never deleted by this). requested -> confirmed by the emailed single-use link (only its hash is stored) -> scheduled for the end of the
    # grace period -> anonymised by the hourly job (`deleted_at`). A completed deletion keeps a tombstone row with no personal data, so history that points at the person points at nobody.
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_token_hash: Mapped[str | None] = mapped_column(String(64))
    deletion_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deletion_scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    memberships: Mapped[list["Membership"]] = relationship(back_populates="user")

    @property
    def has_local_login(self) -> bool:
        return bool(self.password_hash)

    @property
    def google_linked(self) -> bool:
        return bool(self.google_sub)


class Membership(IdMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_membership_tenant_user"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[Role] = mapped_column(Enum(Role, name="role"), default=Role.staff)
    # Staff only: FALSE restricts the member to the locations listed in membership_locations. Owners/admins always see all.
    all_locations: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    tenant: Mapped[Tenant] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")


class MembershipLocation(IdMixin, Base):
    """A location a restricted staff member may access (see core/deps.py: TenantContext.location_ids)."""

    __tablename__ = "membership_locations"
    __table_args__ = (UniqueConstraint("membership_id", "location_id", name="uq_membership_location"),
                      Index("ix_membership_locations_tenant", "tenant_id"))

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    membership_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("memberships.id", ondelete="CASCADE"))
    location_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locations.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuthSession(IdMixin, Base):
    """Server-side session. The cookie holds an opaque token; only its SHA-256 is stored."""

    __tablename__ = "auth_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    active_tenant_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tenants.id", ondelete="SET NULL"))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Invitation(IdMixin, TimestampMixin, Base):
    __tablename__ = "invitations"
    __table_args__ = (Index("ix_invitations_tenant_email", "tenant_id", "email"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(254))
    role: Mapped[Role] = mapped_column(Enum(Role, name="role"), default=Role.staff)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    location_ids: Mapped[list | None] = mapped_column(JSONB)  # staff invitations only: NULL = every location
    # Owner-claim invitations only: the sign-up allowlist row THIS invitation created (NULL when the address was already listed). Only such a row may be removed when the claim is revoked.
    allowlist_entry_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("registration_allowlist.id", ondelete="SET NULL"))


class PasswordResetToken(IdMixin, Base):
    __tablename__ = "password_reset_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailVerificationToken(IdMixin, Base):
    __tablename__ = "email_verification_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
