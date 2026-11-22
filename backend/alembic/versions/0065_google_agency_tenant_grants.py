"""Agency tenant grants: which businesses a FlowHQ operator has opened the internal agency path for (docs/audits/GOOGLE_PROJECT_ARCHITECTURE_OPTIONS.md, internal-only operation).

Revision ID: 0065
Revises: 0064

Additive. PLATFORM-ONLY (row-level security admits the bypass context and nothing else): a business can neither read nor write its own grant. A grant is the OPERATOR's decision that a business may start the agency
path; it is NOT the client's consent (that is recorded separately, by the client's own administrator, in google_agency_authorizations). One open (not revoked) grant per business; revoking keeps the row.
"""
import os

import sqlalchemy as sa
from alembic import op

revision = "0065"
down_revision = "0064"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
PLATFORM_ONLY = "current_setting('app.bypass_rls', true) = 'on'"


def upgrade() -> None:
    op.create_table(
        "google_agency_tenant_grants",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("granted_by_email", sa.String(254), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("note", sa.String(300)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)), sa.Column("revoked_by_email", sa.String(254)),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.CheckConstraint("revoked_at IS NULL OR revoked_by_email IS NOT NULL", name="ck_gagency_grant_revoked_by"),
    )
    op.create_index("uq_gagency_grant_open", "google_agency_tenant_grants", ["tenant_id"], unique=True, postgresql_where=sa.text("revoked_at IS NULL"))
    op.execute("ALTER TABLE google_agency_tenant_grants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE google_agency_tenant_grants FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY platform_only ON google_agency_tenant_grants USING ({PLATFORM_ONLY}) WITH CHECK ({PLATFORM_ONLY})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON google_agency_tenant_grants TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_table("google_agency_tenant_grants")
