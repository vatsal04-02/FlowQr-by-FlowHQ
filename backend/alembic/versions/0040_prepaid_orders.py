"""Prepaid plan orders (one-time Cashfree Payment Gateway purchases of 1, 3, 6 or 12 months).

Revision ID: 0040
Revises: 0037

One new tenant table, RLS forced with the same tenant policy as every tenant table. The app role may SELECT, INSERT and UPDATE (an order is never deleted; it leaves with the business through the
foreign-key cascade). Additive only: nothing existing changes and no row is written. Downgrade drops the table (an order is a payment record: take a backup first).

Numbering: 0038 (consent grants) and 0039 (trial grants) exist on other branches that are not released, so this takes 0040 to keep the ids unique. It chains on production's head 0037 so this branch
builds and tests on its own. WHEN 0038/0039 LAND FIRST, change ONE line: `down_revision` to the then-current head (see docs/CARDLESS_TRIAL.md section 3 for the same procedure).
"""
import os

import sqlalchemy as sa
from alembic import op

revision = "0040"
down_revision = "0037"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "prepaid_orders",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("created_by", sa.UUID()),
        sa.Column("plan_code", sa.String(32), nullable=False),
        sa.Column("months", sa.Integer(), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(16), nullable=False, server_default="created"),
        sa.Column("order_id", sa.String(40), nullable=False),
        sa.Column("cf_order_id", sa.String(32)),
        sa.Column("cf_payment_id", sa.String(32)),
        sa.Column("payment_method", sa.String(24)),
        sa.Column("failure_reason", sa.String(300)),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
        sa.Column("period_start", sa.DateTime(timezone=True)),
        sa.Column("period_end", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("order_id", name="uq_prepaid_orders_order_id"),
        sa.CheckConstraint("months in (1, 3, 6, 12)", name="ck_prepaid_orders_months"),
        sa.CheckConstraint("amount_paise > 0", name="ck_prepaid_orders_amount"),
    )
    op.create_index("ix_prepaid_orders_tenant", "prepaid_orders", ["tenant_id", "created_at"])
    op.execute("ALTER TABLE prepaid_orders ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE prepaid_orders FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON prepaid_orders USING ({COND}) WITH CHECK ({COND})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON prepaid_orders TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_table("prepaid_orders")
