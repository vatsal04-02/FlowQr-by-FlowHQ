"""Geo-grid ranking, and the link that lets posts, photos and replies be governed by the same action engine as profile edits.

Revision ID: 0028
Revises: 0027

* rank_grids / rank_grid_scans / rank_grid_points: tenant-scoped, RLS enabled AND forced. Cost: every point is one billed Places search, counted per business per month.
* agent_actions.subject_type / subject_id: an action may govern one scheduled post, photo or reply draft (policy, approval evidence, claim, read-back, history)
  instead of one profile field. NULL for the original profile-field actions.
"""
import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
TABLES = ("rank_grids", "rank_grid_scans", "rank_grid_points")


def _grant(table: str, privileges: str) -> None:
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT {privileges} ON {table} TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({COND}) WITH CHECK ({COND})")


def _base():
    return [sa.Column("id", sa.UUID(), nullable=False)]


def upgrade() -> None:
    op.add_column("agent_actions", sa.Column("subject_type", sa.String(16)))
    op.add_column("agent_actions", sa.Column("subject_id", sa.UUID()))
    op.create_index("ix_agent_actions_subject", "agent_actions", ["subject_type", "subject_id"])

    op.create_table(
        "rank_grids", *_base(),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("google_location_id", sa.UUID(), sa.ForeignKey("google_locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(60), nullable=False),
        sa.Column("mode", sa.String(8), nullable=False, server_default="square"),
        sa.Column("center_lat", sa.Float()), sa.Column("center_lng", sa.Float()),
        sa.Column("size", sa.SmallInteger()), sa.Column("spacing_m", sa.Integer()),
        sa.Column("points", JSONB(), nullable=False, server_default="[]"),
        sa.Column("points_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("google_location_id", "name", name="uq_rank_grid_name"),
        sa.CheckConstraint("mode in ('square','custom')", name="ck_rank_grid_mode"),
    )
    op.create_index("ix_rank_grids_tenant", "rank_grids", ["tenant_id"])

    op.create_table(
        "rank_grid_scans", *_base(),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("google_location_id", sa.UUID(), sa.ForeignKey("google_locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("grid_id", sa.UUID(), sa.ForeignKey("rank_grids.id", ondelete="CASCADE"), nullable=False),
        sa.Column("keyword_id", sa.UUID(), sa.ForeignKey("rank_keywords.id", ondelete="CASCADE"), nullable=False),
        sa.Column("points_hash", sa.String(64), nullable=False),
        sa.Column("source", sa.String(8), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(8), nullable=False, server_default="running"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("points_total", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("points_ok", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("points_found", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("arp", sa.Float()), sa.Column("atrp", sa.Float()), sa.Column("solv", sa.Float()), sa.Column("coverage", sa.Float()),
        sa.Column("calls", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("change", JSONB()),
        sa.Column("error", sa.Text()),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status in ('running','done','partial','failed')", name="ck_rank_grid_scan_status"),
    )
    op.create_index("ix_rank_grid_scans_grid", "rank_grid_scans", ["grid_id", "keyword_id", "started_at"])
    op.create_index("ix_rank_grid_scans_tenant", "rank_grid_scans", ["tenant_id", "started_at"])

    op.create_table(
        "rank_grid_points", *_base(),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("scan_id", sa.UUID(), sa.ForeignKey("rank_grid_scans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("point_index", sa.SmallInteger(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False), sa.Column("lng", sa.Float(), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("rank", sa.SmallInteger()), sa.Column("results_seen", sa.SmallInteger()),
        sa.Column("error", sa.Text()),
        sa.Column("checked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scan_id", "point_index", name="uq_rank_grid_point"),
        sa.CheckConstraint("status in ('ok','error')", name="ck_rank_grid_point_status"),
    )
    op.create_index("ix_rank_grid_points_scan_id", "rank_grid_points", ["scan_id"])
    op.create_index("ix_rank_grid_points_tenant_month", "rank_grid_points", ["tenant_id", "checked_at"])

    for t in TABLES:
        _rls(t)
        _grant(t, "SELECT, INSERT, UPDATE, DELETE")
    # Retention (services/agent/retention.py) erases FINISHED actions whole. Deleting an action cascades to its append-only history, which the trigger still refuses
    # unless the transaction-local erase flag is set, so this privilege cannot be used to quietly remove history.
    _grant("agent_actions", "DELETE")


def downgrade() -> None:
    for t in reversed(TABLES):
        op.drop_table(t)
    op.drop_index("ix_agent_actions_subject", table_name="agent_actions")
    op.drop_column("agent_actions", "subject_id")
    op.drop_column("agent_actions", "subject_type")
