"""Pinned competitors and their dated snapshots (Competitor Analysis, stage 2).

Revision ID: 0036
Revises: 0035

Two new tenant tables, RLS forced with the same tenant policy as every tenant table. Snapshots are written only from Google Places results the business's own rank checks already
received (no extra Google call). The app role gets SELECT/INSERT/UPDATE/DELETE on pinned_competitors (unfollowing deletes the row; its snapshots go with it through the foreign-key cascade) and only SELECT/INSERT on competitor_snapshots (observations are append-only); rows leave with the
business through the foreign-key cascades. Additive only: nothing existing changes. Downgrade drops both tables (observations are re-collected from new checks, never rebuilt).
Chain: 0033 (production) -> 0035 -> 0036. See docs/MIGRATION_RECONCILIATION.md for how this lines up with the Cashfree branch.
"""
import os

from alembic import op
import sqlalchemy as sa

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def _rls(table: str, privileges: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({COND}) WITH CHECK ({COND})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT {privileges} ON {table} TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def upgrade() -> None:
    op.create_table(
        "pinned_competitors",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("google_location_id", sa.UUID(), nullable=False),
        sa.Column("place_id", sa.String(200), nullable=False),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("created_by", sa.UUID()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["google_location_id"], ["google_locations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("google_location_id", "place_id", name="uq_pinned_competitor"),
    )
    op.create_index("ix_pinned_competitors_tenant", "pinned_competitors", ["tenant_id"])
    _rls("pinned_competitors", "SELECT, INSERT, UPDATE, DELETE")
    op.create_table(
        "competitor_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("competitor_id", sa.UUID(), nullable=False),
        sa.Column("rank_check_id", sa.UUID()),
        sa.Column("keyword_id", sa.UUID()),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rating", sa.Float()),
        sa.Column("reviews", sa.Integer()),
        sa.Column("position", sa.SmallInteger()),
        sa.Column("your_position", sa.SmallInteger()),
        sa.Column("source", sa.String(16), nullable=False, server_default="rank_check"),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["competitor_id"], ["pinned_competitors.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rank_check_id"], ["rank_checks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["keyword_id"], ["rank_keywords.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("competitor_id", "rank_check_id", name="uq_competitor_snapshot_check"),
        sa.CheckConstraint("source in ('rank_check')", name="ck_competitor_snapshot_source"),
    )
    op.create_index("ix_competitor_snapshots_competitor", "competitor_snapshots", ["competitor_id", "observed_at"])
    _rls("competitor_snapshots", "SELECT, INSERT")


def downgrade() -> None:
    op.drop_table("competitor_snapshots")
    op.drop_table("pinned_competitors")
