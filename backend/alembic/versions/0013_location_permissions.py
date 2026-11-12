"""Location-level permissions for staff.

memberships.all_locations (default TRUE, so every existing member keeps exactly the access they have today) plus
membership_locations (which locations a restricted staff member may see). Owners and admins always have every location.
invitations.location_ids carries the restriction through an invitation. Additive and reversible.

Revision ID: 0013
Revises: 0012
"""
import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.add_column("memberships", sa.Column("all_locations", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("invitations", sa.Column("location_ids", postgresql.JSONB(), nullable=True))
    op.create_table(
        "membership_locations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("membership_id", sa.UUID(), nullable=False),
        sa.Column("location_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("membership_id", "location_id", name="uq_membership_location"),
    )
    op.create_index("ix_membership_locations_tenant", "membership_locations", ["tenant_id"])
    op.execute("ALTER TABLE membership_locations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE membership_locations FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON membership_locations USING ({COND}) WITH CHECK ({COND})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON membership_locations TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON membership_locations")
    op.drop_index("ix_membership_locations_tenant", table_name="membership_locations")
    op.drop_table("membership_locations")
    op.drop_column("invitations", "location_ids")
    op.drop_column("memberships", "all_locations")
