"""Temporary, per-business prepaid price overrides (the ₹1 Growth test offer), kept apart from the permanent price list.

Revision ID: 0041
Revises: 0040

A row says: THIS business may buy THIS plan for THIS number of months at THIS amount, once, until THIS time. The permanent list (services/plans.py TERM_PRICES_PAISE) is never edited; the original price is
recorded on every order (`prepaid_orders.list_price_paise`) and on the override itself. An override is single-use (`used_order_id`), expires (`expires_at`, mandatory) and can be revoked.
Additive only: two nullable columns on prepaid_orders and one new tenant table (RLS forced). The app role can SELECT, INSERT and UPDATE (never DELETE: an override is an audit record).
Numbering: 0040 prepaid orders sits underneath. 0038 (consent) and 0039 (trial) are on other unreleased branches; whoever lands second changes one `down_revision` line.
"""
import os

import sqlalchemy as sa
from alembic import op

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "prepaid_price_overrides",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("plan_code", sa.String(32), nullable=False),
        sa.Column("months", sa.Integer(), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("list_price_paise", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(60), nullable=False, server_default="Test price"),
        sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("used_order_id", sa.UUID()),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["used_order_id"], ["prepaid_orders.id"], ondelete="SET NULL"),
        sa.CheckConstraint("amount_paise >= 100", name="ck_prepaid_override_amount"),
        sa.CheckConstraint("amount_paise < list_price_paise", name="ck_prepaid_override_cheaper"),  # an override can only ever lower a price, never raise it
        sa.CheckConstraint("months in (1, 3, 6, 12)", name="ck_prepaid_override_months"),
    )
    op.create_index("ix_prepaid_overrides_tenant", "prepaid_price_overrides", ["tenant_id", "created_at"])
    op.execute("ALTER TABLE prepaid_price_overrides ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE prepaid_price_overrides FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON prepaid_price_overrides USING ({COND}) WITH CHECK ({COND})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON prepaid_price_overrides TO {APP_ROLE}';
          END IF;
        END $$;
    """)
    op.add_column("prepaid_orders", sa.Column("list_price_paise", sa.Integer()))
    op.add_column("prepaid_orders", sa.Column("override_id", sa.UUID()))
    op.create_foreign_key("fk_prepaid_orders_override", "prepaid_orders", "prepaid_price_overrides", ["override_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_prepaid_orders_override", "prepaid_orders", type_="foreignkey")
    op.drop_column("prepaid_orders", "override_id")
    op.drop_column("prepaid_orders", "list_price_paise")
    op.drop_table("prepaid_price_overrides")
