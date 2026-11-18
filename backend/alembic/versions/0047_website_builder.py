"""Website builder: sites, hostname registry, images, enquiries, publish history, slug quarantine.

Revision ID: 0047
Revises: 0046

Additive only: six new tables and ONE new nullable column (tenants.website_interest, what the business said about having a website during onboarding); nothing existing is read, changed or rewritten. Production must be at 0046 first.
Numbering: 0047 was verified free across every local and remote branch on 2026-11-19. `feature/cardless-trial` still carries a migration numbered 0039 on top of 0037; whichever of the
two ships second must renumber to the next free number and re-point `down_revision` (docs/WEBSITE_BUILDER.md, "Migration graph").

* sites               one website per business (unique tenant_id): template, draft and published content, publish state, and the manually recorded commercial status.
* site_domains        the hostname registry; one ACTIVE primary hostname per site (partial unique index); hostnames are unique and lower case.
* site_assets         uploaded images, re-encoded (no EXIF/GPS); unique per site by checksum.
* site_enquiries      messages from a website's enquiry form (consent time recorded, keyed IP hash only).
* site_revisions      append-only history of every successful publish (the application role can SELECT and INSERT, nothing else).
* site_slug_quarantine  released site names, held 90 days. Platform-only: row-level security admits the bypass context and nothing else.
Tenant tables get forced row-level security with the usual tenant policy. No user, membership, subscription or card row is created or altered.
"""
import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0047"
down_revision = "0046"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
PLATFORM_ONLY = "current_setting('app.bypass_rls', true) = 'on'"
TS = lambda: [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),  # noqa: E731
              sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def _in(col, values):
    return f"{col} in ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.add_column("tenants", sa.Column("website_interest", sa.String(12), nullable=True))  # has_site | wants_site | not_now; NULL = never asked
    op.create_check_constraint("ck_tenants_website_interest", "tenants", "website_interest IS NULL OR website_interest IN ('has_site','wants_site','not_now')")
    op.create_table(
        "sites",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("site_slug", sa.String(40), nullable=False),
        sa.Column("template_key", sa.String(24), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(12), nullable=False, server_default="draft"),
        sa.Column("draft_content", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("draft_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("published_content", JSONB()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("published_by", sa.UUID()),
        sa.Column("live_version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("publish_counter", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("publish_state", sa.String(12), nullable=False, server_default="idle"),
        sa.Column("publish_error", sa.String(300)),
        sa.Column("publish_attempted_at", sa.DateTime(timezone=True)),
        sa.Column("commercial_status", sa.String(14), nullable=False),
        sa.Column("commercial_reason", sa.String(300)),
        sa.Column("billing_period", sa.String(8)),
        sa.Column("paid_until", sa.Date()),
        sa.Column("grace_until", sa.DateTime(timezone=True)),
        sa.Column("commercial_updated_by", sa.UUID()),
        sa.Column("commercial_updated_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.UUID()),
        sa.Column("updated_by", sa.UUID()),
        *TS(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["published_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["commercial_updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", name="uq_sites_tenant"),
        sa.UniqueConstraint("site_slug", name="uq_sites_slug"),
        sa.CheckConstraint(_in("status", ("draft", "published", "unpublished", "suspended")), name="ck_sites_status"),
        sa.CheckConstraint(_in("commercial_status", ("complimentary", "paid_offline", "expired", "suspended")), name="ck_sites_commercial"),
        sa.CheckConstraint(_in("publish_state", ("idle", "publishing", "failed")), name="ck_sites_publish_state"),
        sa.CheckConstraint("site_slug = lower(site_slug)", name="ck_sites_slug_lower"),
    )
    op.create_table(
        "site_domains",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("hostname", sa.String(253), nullable=False),
        sa.Column("domain_type", sa.String(8), nullable=False, server_default="hosted"),
        sa.Column("status", sa.String(10), nullable=False, server_default="active"),
        sa.Column("verification", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.true()),
        *TS(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("hostname", name="uq_site_domains_hostname"),
        sa.CheckConstraint(_in("domain_type", ("hosted", "custom")), name="ck_site_domains_type"),
        sa.CheckConstraint(_in("status", ("active", "pending", "verified", "failed", "removed")), name="ck_site_domains_status"),
        sa.CheckConstraint("hostname = lower(hostname)", name="ck_site_domains_lower"),
    )
    op.create_index("ix_site_domains_site_id", "site_domains", ["site_id"])
    op.create_index("uq_site_domains_primary", "site_domains", ["site_id"], unique=True, postgresql_where=sa.text("is_primary AND status = 'active'"))
    op.create_table(
        "site_assets",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False, server_default="photo"),
        sa.Column("content_type", sa.String(24), nullable=False, server_default="image/webp"),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("alt_text", sa.String(200), nullable=False, server_default=""),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_key", sa.String(120), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        *TS(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("site_id", "sha256", name="uq_site_assets_site_sha"),
    )
    op.create_index("ix_site_assets_site_id", "site_assets", ["site_id"])
    op.create_table(
        "site_enquiries",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("phone", sa.String(32)),
        sa.Column("email", sa.String(254)),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("consent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="new"),
        sa.Column("ip_hash", sa.String(64)),
        sa.Column("contacted_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("handled_by", sa.UUID()),
        *TS(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["handled_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(_in("status", ("new", "contacted", "resolved", "spam")), name="ck_site_enquiries_status"),
    )
    op.create_index("ix_site_enquiries_site_created", "site_enquiries", ["site_id", "created_at"])
    op.create_table(
        "site_revisions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("site_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("hosting_version", sa.Integer(), nullable=False),
        sa.Column("content", JSONB(), nullable=False),
        sa.Column("template_key", sa.String(24), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("editor", sa.UUID()),
        sa.Column("note", sa.String(200)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["editor"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("site_id", "revision", name="uq_site_revisions_number"),
    )
    op.create_index("ix_site_revisions_site_id", "site_revisions", ["site_id"])
    op.create_table(
        "site_slug_quarantine",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(40), nullable=False),
        sa.Column("former_tenant_id", sa.UUID()),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("release_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(40), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_site_slug_quarantine_slug"),
    )
    for t in ("sites", "site_domains", "site_assets", "site_enquiries", "site_revisions"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({COND}) WITH CHECK ({COND})")
    op.execute("ALTER TABLE site_slug_quarantine ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE site_slug_quarantine FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY platform_only ON site_slug_quarantine USING ({PLATFORM_ONLY}) WITH CHECK ({PLATFORM_ONLY})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON sites, site_domains, site_assets, site_enquiries TO {APP_ROLE}';
            EXECUTE 'GRANT SELECT, INSERT ON site_revisions TO {APP_ROLE}';
            EXECUTE 'GRANT SELECT, INSERT, DELETE ON site_slug_quarantine TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    for t in ("site_slug_quarantine", "site_revisions", "site_enquiries", "site_assets", "site_domains", "sites"):
        op.drop_table(t)
    op.drop_constraint("ck_tenants_website_interest", "tenants", type_="check")
    op.drop_column("tenants", "website_interest")
