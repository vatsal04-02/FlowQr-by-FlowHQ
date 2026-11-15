"""Local rank tracking: keywords to watch per Google location, a history of measured positions, cached coordinates.

Revision ID: 0023
Revises: 0022
"""
import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
TABLES = ("rank_keywords", "rank_checks")


def _ts(name="created_at"):
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)


def upgrade() -> None:
    op.add_column("google_locations", sa.Column("lat", sa.Float()))
    op.add_column("google_locations", sa.Column("lng", sa.Float()))

    op.create_table(
        "rank_keywords",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("google_location_id", sa.UUID(), sa.ForeignKey("google_locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("keyword", sa.String(80), nullable=False),
        sa.Column("created_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        _ts(), _ts("updated_at"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("google_location_id", "keyword", name="uq_rank_keyword_location"),
    )
    op.create_index("ix_rank_keywords_tenant", "rank_keywords", ["tenant_id"])

    op.create_table(
        "rank_checks",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("keyword_id", sa.UUID(), sa.ForeignKey("rank_keywords.id", ondelete="CASCADE"), nullable=False),
        sa.Column("google_location_id", sa.UUID(), sa.ForeignKey("google_locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),  # ok | error
        sa.Column("rank", sa.SmallInteger()),  # 1-based position, NULL when not in the results that were read
        sa.Column("results_seen", sa.SmallInteger()),  # how many results Google returned (the rank is only meaningful within these)
        sa.Column("top_results", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),  # [{place_id, name, rating, reviews, is_you}]
        sa.Column("error", sa.Text()),
        sa.Column("source", sa.String(8), nullable=False, server_default="manual"),  # manual | auto
        sa.Column("center_lat", sa.Float()),
        sa.Column("center_lng", sa.Float()),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status in ('ok','error')", name="ck_rank_check_status"),
    )
    op.create_index("ix_rank_checks_keyword", "rank_checks", ["keyword_id", "checked_at"])
    op.create_index("ix_rank_checks_tenant_month", "rank_checks", ["tenant_id", "checked_at"])

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({COND}) WITH CHECK ({COND})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON {", ".join(TABLES)} TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.drop_table(table)
    op.drop_column("google_locations", "lng")
    op.drop_column("google_locations", "lat")
