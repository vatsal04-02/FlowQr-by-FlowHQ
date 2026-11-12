"""Tenants, users, memberships, auth sessions, invitations, reset tokens."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint, text
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
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspension_reason: Mapped[str | None] = mapped_column(String(300))
    deletion_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # owner asked to delete the business
    deletion_scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # when the daily job will do it (cancellable until then)
    support_status: Mapped[str] = mapped_column(String(16), default="none")  # none | open | waiting | resolved
    support_note: Mapped[str | None] = mapped_column(Text)
    # Review Growth business context, owner-edited: {category_key, description, services[], disabled_suggestions[], languages[]}
    review_context: Mapped[dict] = mapped_column(JSONB, default=dict, server_default=text("'{}'::jsonb"))

    memberships: Mapped[list["Membership"]] = relationship(back_populates="tenant")


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(254), unique=True)  # stored lower-cased
    # NULL for accounts created through "Continue with Google" until the user sets a password.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    # Google's stable account id (the ID token `sub`). Never derived from, or matched by, email alone.
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(32))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

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
