"""Website builder: a static website an administrator builds and publishes for a business that has no website.

Phase 1 is administrator-managed: no shopkeeper login is involved. `draft_content` is what the editor changes; `published_content` is the validated snapshot the hosting provider was last given.
Only the snapshot is ever published, so a draft can never leak. Everything tenant-owned carries a tenant_id and forced row-level security like every other tenant table; the slug quarantine
is platform-only (a freed name must not be re-registered by someone else for 90 days)."""
import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.models.base import IdMixin, TimestampMixin

SITE_STATUSES = ("draft", "published", "unpublished", "suspended")
COMMERCIAL_STATUSES = ("complimentary", "paid_offline", "expired", "suspended", "not_activated")  # not_activated: an owner generated the draft; it can never be published until an administrator records hosting
GENERATION_STATUSES = ("queued", "running", "completed", "failed")
PUBLISH_STATES = ("idle", "publishing", "failed")
DOMAIN_TYPES = ("hosted", "custom")
DOMAIN_STATUSES = ("active", "pending", "verified", "failed", "removed")
ENQUIRY_STATUSES = ("new", "contacted", "resolved", "spam")


def _in(col: str, values) -> str:
    return f"{col} in ({', '.join(repr(v) for v in values)})"


class Site(IdMixin, TimestampMixin, Base):
    __tablename__ = "sites"
    __table_args__ = (
        CheckConstraint(_in("status", SITE_STATUSES), name="ck_sites_status"),
        CheckConstraint(_in("commercial_status", COMMERCIAL_STATUSES), name="ck_sites_commercial"),
        CheckConstraint(_in("publish_state", PUBLISH_STATES), name="ck_sites_publish_state"),
        CheckConstraint("site_slug = lower(site_slug)", name="ck_sites_slug_lower"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), unique=True)  # one website per business in Phase 1
    site_slug: Mapped[str] = mapped_column(String(40), unique=True)
    template_key: Mapped[str] = mapped_column(String(24))
    template_version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(12), default="draft")
    draft_content: Mapped[dict] = mapped_column(JSONB, default=dict)
    draft_version: Mapped[int] = mapped_column(Integer, default=1)  # optimistic concurrency: a save must name the version it started from
    published_content: Mapped[dict | None] = mapped_column(JSONB)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    live_version: Mapped[int] = mapped_column(Integer, default=0)  # the hosting version the public currently sees (0 = never published)
    publish_counter: Mapped[int] = mapped_column(Integer, default=0)  # highest version number ever attempted (a failed attempt still uses its number)
    publish_state: Mapped[str] = mapped_column(String(12), default="idle")
    publish_error: Mapped[str | None] = mapped_column(String(300))
    publish_attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Commercial status is recorded by hand (no billing is connected). Hosting is never silently free: creating a site needs an explicit status, and `complimentary` needs a reason.
    commercial_status: Mapped[str] = mapped_column(String(14))
    commercial_reason: Mapped[str | None] = mapped_column(String(300))
    billing_period: Mapped[str | None] = mapped_column(String(8))  # monthly | annual (information only)
    paid_until: Mapped[date | None] = mapped_column(Date)
    grace_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # set when hosting expires: the site stays up until then, content is never deleted by lapse
    commercial_updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    commercial_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class SiteDomain(IdMixin, TimestampMixin, Base):
    """The hostname registry. Tenant resolution only ever trusts a hostname that is listed here (or derived from a live site's slug by the same rules); custom domains are a later phase."""

    __tablename__ = "site_domains"
    __table_args__ = (
        CheckConstraint(_in("domain_type", DOMAIN_TYPES), name="ck_site_domains_type"),
        CheckConstraint(_in("status", DOMAIN_STATUSES), name="ck_site_domains_status"),
        CheckConstraint("hostname = lower(hostname)", name="ck_site_domains_lower"),
        Index("uq_site_domains_primary", "site_id", unique=True, postgresql_where=text("is_primary AND status = 'active'")),  # one active primary hostname per site
    )

    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    hostname: Mapped[str] = mapped_column(String(253), unique=True)
    domain_type: Mapped[str] = mapped_column(String(8), default="hosted")
    status: Mapped[str] = mapped_column(String(10), default="active")
    verification: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True)


class SiteAsset(IdMixin, TimestampMixin, Base):
    """An uploaded image, stored only as the re-encoded derivative (EXIF and GPS removed). Bytes live in the database like the other uploads; the published copy goes to the hosting provider."""

    __tablename__ = "site_assets"
    __table_args__ = (UniqueConstraint("site_id", "sha256", name="uq_site_assets_site_sha"),)

    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(8), default="photo")  # photo | logo
    content_type: Mapped[str] = mapped_column(String(24), default="image/webp")
    size_bytes: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    alt_text: Mapped[str] = mapped_column(String(200), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    storage_key: Mapped[str] = mapped_column(String(120))  # assets/<sha16>.webp inside the published site
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)


class SiteEnquiry(IdMixin, TimestampMixin, Base):
    """A message a visitor sent through a website's enquiry form. Never shown publicly; kept for SITES_ENQUIRY_RETENTION_DAYS."""

    __tablename__ = "site_enquiries"
    __table_args__ = (CheckConstraint(_in("status", ENQUIRY_STATUSES), name="ck_site_enquiries_status"), Index("ix_site_enquiries_site_created", "site_id", "created_at"))

    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(32))
    email: Mapped[str | None] = mapped_column(String(254))
    message: Mapped[str] = mapped_column(Text)
    consent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10), default="new")
    ip_hash: Mapped[str | None] = mapped_column(String(64))  # keyed hash for abuse checks only, never the address
    contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handled_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class SiteRevision(IdMixin, Base):
    """Append-only: the content of every successful publish. Rolling back publishes an older revision as a new one; nothing here is ever edited."""

    __tablename__ = "site_revisions"
    __table_args__ = (UniqueConstraint("site_id", "revision", name="uq_site_revisions_number"),)

    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    revision: Mapped[int] = mapped_column(Integer)
    hosting_version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSONB)
    template_key: Mapped[str] = mapped_column(String(24))
    template_version: Mapped[int] = mapped_column(Integer)
    editor: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    note: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SiteSlugQuarantine(IdMixin, Base):
    """A site name that was released (site deleted, or renamed) cannot be taken by another business for 90 days, so a freed address cannot be used to impersonate it.
    Platform-only. `former_tenant_id` lets the business that held the name take it back."""

    __tablename__ = "site_slug_quarantine"

    slug: Mapped[str] = mapped_column(String(40), unique=True)
    former_tenant_id: Mapped[uuid.UUID | None] = mapped_column()
    released_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    release_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reason: Mapped[str] = mapped_column(String(40))


class SiteGenerationJob(IdMixin, TimestampMixin, Base):
    """One AI website generation: what has really happened, step by step. At most one queued or running job per business (partial unique index)."""

    __tablename__ = "site_generation_jobs"
    __table_args__ = (
        CheckConstraint(_in("status", GENERATION_STATUSES), name="ck_site_generation_status"),
        Index("ix_site_generation_tenant", "tenant_id", "created_at"),
        Index("uq_site_generation_active", "tenant_id", unique=True, postgresql_where=text("status in ('queued', 'running')")),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    site_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sites.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(10), default="queued", server_default="queued")
    stage: Mapped[str] = mapped_column(String(32), default="INITIALIZING", server_default="INITIALIZING")
    steps: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    notes: Mapped[list] = mapped_column(JSONB, default=list, server_default=text("'[]'::jsonb"))
    error: Mapped[str | None] = mapped_column(String(300))
    trigger: Mapped[str] = mapped_column(String(16))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
