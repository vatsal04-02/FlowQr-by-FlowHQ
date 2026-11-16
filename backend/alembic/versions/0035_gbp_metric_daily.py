"""Google Business Profile daily metrics history (gbp_metric_daily).

Revision ID: 0035
Revises: 0033

Revision numbering (see docs/MIGRATION_RECONCILIATION.md):
* Production is at 0033 (checked read-only on the VPS, 2026-11-16). This revision revises 0033, so the path from production is 0033 -> 0035 with one head.
* 0034 is deliberately NOT used here: the unmerged billing/cashfree-phase1 branch already owns the id "0034" (its file is 0034_cashfree_billing.py, parented on 0032, and it
  assumes 0033 was never applied, which is no longer true). Reusing 0034 would give two revisions with one id. When that branch is rebased, its revision must be re-parented
  onto 0033 (or this one) and renumbered; that is a decision for that branch, not made here.

Additive only: one new table, RLS forced with the same tenant policy as every tenant table, app role gets SELECT/INSERT/UPDATE (no DELETE: rows leave with the business through
the foreign-key cascade). No existing table or column changes. Downgrade drops the table (the history is lost; it is re-collected from Google going forward, never rebuilt).
"""
import os

from alembic import op
import sqlalchemy as sa

revision = "0035"
down_revision = "0033"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "gbp_metric_daily",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("google_location_id", sa.UUID(), nullable=False),
        sa.Column("metric", sa.String(48), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("value", sa.BigInteger(), nullable=False),
        sa.Column("source", sa.String(40), nullable=False, server_default="gbp_performance_api"),
        sa.Column("first_fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["google_location_id"], ["google_locations.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("google_location_id", "metric", "day", name="uq_gbp_metric_daily"),
        sa.CheckConstraint("value >= 0", name="ck_gbp_metric_value"),
    )
    op.create_index("ix_gbp_metric_tenant_day", "gbp_metric_daily", ["tenant_id", "day"])
    op.execute("ALTER TABLE gbp_metric_daily ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE gbp_metric_daily FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON gbp_metric_daily USING ({COND}) WITH CHECK ({COND})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON gbp_metric_daily TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_table("gbp_metric_daily")
