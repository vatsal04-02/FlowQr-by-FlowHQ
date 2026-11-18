"""Admin-managed businesses: who created a business and how, a contact person, and the offline onboarding agreement record.

Revision ID: 0046
Revises: 0045

Additive only. Nothing about an existing business changes: `origin` is back-filled as 'self_service' by its default, the new people columns are NULL.
* tenants: contact_name (the person at the shop, optional), origin ('self_service' | 'admin'), created_by and updated_by (the user, normally a platform administrator, who created or last
  edited the record through the admin console; NULL for every existing row).
* tenant_agreements: append-only record that a FLOWQR ADMINISTRATOR recorded an offline agreement on behalf of a business (who, when, which terms version, how it was recorded, a note).
  It is NOT a personal acceptance by the shopkeeper and implies no age confirmation; the row carries that statement. Tenant table: RLS forced like every other; the app role can SELECT and INSERT.
* invitations.allowlist_entry_id: which sign-up allowlist row a claim invitation created, so revoking the claim can remove exactly that row (and never one an administrator added by hand).
* data_requests / data_request_events: administrator-handled export and deletion requests for a business that has no owner login. Platform-only (row-level security admits the bypass context
  only); the request outlives the business it is about (tenant_id SET NULL, name snapshot); events are append-only. Nothing is deleted or sent by the database or by a job.
No user, membership or subscription row is created or altered by this migration.
"""
import os

import sqlalchemy as sa
from alembic import op

revision = "0046"
down_revision = "0045"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
PLATFORM_ONLY = "current_setting('app.bypass_rls', true) = 'on'"


def upgrade() -> None:
    op.add_column("tenants", sa.Column("contact_name", sa.String(120)))
    op.add_column("tenants", sa.Column("origin", sa.String(12), nullable=False, server_default="self_service"))
    op.add_column("tenants", sa.Column("created_by", sa.UUID()))
    op.add_column("tenants", sa.Column("updated_by", sa.UUID()))
    op.create_foreign_key("fk_tenants_created_by", "tenants", "users", ["created_by"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_tenants_updated_by", "tenants", "users", ["updated_by"], ["id"], ondelete="SET NULL")
    op.create_check_constraint("ck_tenants_origin", "tenants", "origin in ('self_service', 'admin')")

    op.create_table(
        "tenant_agreements",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("recorded_by", sa.UUID()),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terms_version", sa.String(40), nullable=False),
        sa.Column("method", sa.String(12), nullable=False),
        sa.Column("note", sa.String(300)),
        sa.Column("statement", sa.String(300), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint("method in ('phone', 'in_person', 'whatsapp', 'paper', 'other')", name="ck_tenant_agreements_method"),
    )
    op.create_index("ix_tenant_agreements_tenant", "tenant_agreements", ["tenant_id", "recorded_at"])
    op.execute("ALTER TABLE tenant_agreements ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_agreements FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON tenant_agreements USING ({COND}) WITH CHECK ({COND})")
    op.add_column("invitations", sa.Column("allowlist_entry_id", sa.UUID()))
    op.create_foreign_key("fk_invitations_allowlist_entry", "invitations", "registration_allowlist", ["allowlist_entry_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "data_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID()),
        sa.Column("business_name", sa.String(200), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="open"),
        sa.Column("requester_name", sa.String(120), nullable=False),
        sa.Column("requester_role", sa.String(14), nullable=False),
        sa.Column("received_via", sa.String(12), nullable=False),
        sa.Column("requester_contact", sa.String(200)),
        sa.Column("request_note", sa.String(300)),
        sa.Column("created_by", sa.UUID()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verification_method", sa.String(24)),
        sa.Column("verification_note", sa.String(300)),
        sa.Column("contact_matched_record", sa.Boolean()),
        sa.Column("verified_by", sa.UUID()),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("eligible_at", sa.DateTime(timezone=True)),
        sa.Column("resolved_by", sa.UUID()),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution", sa.String(300)),
        sa.Column("export_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["verified_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint("kind in ('export', 'deletion')", name="ck_data_requests_kind"),
        sa.CheckConstraint("status in ('open', 'verified', 'fulfilled', 'rejected', 'cancelled')", name="ck_data_requests_status"),
    )
    op.create_index("ix_data_requests_tenant", "data_requests", ["tenant_id"])
    # at most one unresolved request of each kind per business: a second one is a mistake, not a second request
    op.create_index("uq_data_requests_open", "data_requests", ["tenant_id", "kind"], unique=True, postgresql_where=sa.text("status in ('open', 'verified')"))
    op.create_table(
        "data_request_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("request_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID()),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.UUID()),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("detail", sa.String(300)),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["request_id"], ["data_requests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_data_request_events_request", "data_request_events", ["request_id", "at"])
    for t in ("data_requests", "data_request_events"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY platform_only ON {t} USING ({PLATFORM_ONLY}) WITH CHECK ({PLATFORM_ONLY})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT ON tenant_agreements TO {APP_ROLE}';
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON data_requests TO {APP_ROLE}';
            EXECUTE 'GRANT SELECT, INSERT ON data_request_events TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_table("data_request_events")
    op.drop_table("data_requests")
    op.drop_constraint("fk_invitations_allowlist_entry", "invitations", type_="foreignkey")
    op.drop_column("invitations", "allowlist_entry_id")
    op.drop_table("tenant_agreements")
    op.drop_constraint("ck_tenants_origin", "tenants", type_="check")
    op.drop_constraint("fk_tenants_updated_by", "tenants", type_="foreignkey")
    op.drop_constraint("fk_tenants_created_by", "tenants", type_="foreignkey")
    for c in ("updated_by", "created_by", "origin", "contact_name"):
        op.drop_column("tenants", c)
