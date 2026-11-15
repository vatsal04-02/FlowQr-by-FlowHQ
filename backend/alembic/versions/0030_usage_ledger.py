"""One usage ledger for Google and Places calls, richer AI call records, and a per-business Places budget.

Revision ID: 0030
Revises: 0029

* api_usage_ledger: one row per billable or rate-limited external call (Places searches, Business Profile writes), with the operation, the feature that caused it, the number of
  units, the estimated cost (NULL when no price is configured: never 0), and a status of ok, error or refused. Like ai_call_ledger it has NO foreign key to tenants (spend history
  outlives a deleted business) and the app role may only SELECT and INSERT. An idempotency key makes a retry unable to count twice.
* ai_call_ledger gains what a cost review needs: location, actor, request id, retry count, cached tokens, feature.
* tenants.places_monthly_cap: an optional per-business ceiling on Places searches (single checks + map points together), set by a platform admin.
"""
import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def _grant(table: str, privileges: str) -> None:
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT {privileges} ON {table} TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def upgrade() -> None:
    op.create_table(
        "api_usage_ledger",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID()),
        sa.Column("google_location_id", sa.UUID()),
        sa.Column("user_id", sa.UUID()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(24), nullable=False),
        sa.Column("operation", sa.String(48), nullable=False),
        sa.Column("feature", sa.String(32), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("reason", sa.String(200)),
        sa.Column("request_id", sa.String(64)),
        sa.Column("idempotency_key", sa.String(96)),
        sa.Column("est_cost_usd", sa.Numeric(12, 6)),
        sa.Column("priced", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status in ('ok','error','refused')", name="ck_api_usage_status"),
    )
    op.create_index("ix_api_usage_created", "api_usage_ledger", ["created_at"])
    op.create_index("ix_api_usage_tenant_created", "api_usage_ledger", ["tenant_id", "created_at"])
    op.create_index("uq_api_usage_idem", "api_usage_ledger", ["tenant_id", "idempotency_key"], unique=True, postgresql_where=sa.text("idempotency_key IS NOT NULL"))
    op.execute("ALTER TABLE api_usage_ledger ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE api_usage_ledger FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON api_usage_ledger USING ({COND}) WITH CHECK ({COND})")
    _grant("api_usage_ledger", "SELECT, INSERT")

    op.add_column("ai_call_ledger", sa.Column("google_location_id", sa.UUID()))
    op.add_column("ai_call_ledger", sa.Column("actor_user_id", sa.UUID()))
    op.add_column("ai_call_ledger", sa.Column("request_id", sa.String(64)))
    op.add_column("ai_call_ledger", sa.Column("retry_count", sa.SmallInteger()))
    op.add_column("ai_call_ledger", sa.Column("cached_tokens", sa.Integer()))
    op.add_column("ai_call_ledger", sa.Column("feature", sa.String(32)))
    op.add_column("tenants", sa.Column("places_monthly_cap", sa.Integer()))


def downgrade() -> None:
    op.drop_column("tenants", "places_monthly_cap")
    for c in ("feature", "cached_tokens", "retry_count", "request_id", "actor_user_id", "google_location_id"):
        op.drop_column("ai_call_ledger", c)
    op.drop_table("api_usage_ledger")
