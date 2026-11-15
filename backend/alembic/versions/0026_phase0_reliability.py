"""Phase 0 reliability: crash-safe post publishing, per-call AI cost ledger with budgets, reply risk level.

Revision ID: 0026
Revises: 0025

* scheduled_posts: `publishing_started_at` (when the atomic publishing claim was committed), `first_attempt_at` (the first time any attempt could have
  reached Google, so a retry looks for the post before creating another), `publish_token` (random id of the current attempt), and a partial unique
  index so one Google post name can belong to only one FlowQR post per location.
* ai_call_ledger: one row per model call (tokens, model, task, tenant, estimated USD, status). Append-only, no prompt or customer text. It has no foreign
  key on purpose: the spend history that the budgets read must survive a business being deleted.
* tenants.ai_monthly_budget_usd: optional per-business monthly AI budget (NULL = the platform default applies).
* reply_drafts.risk_level: low | medium | high, set when a draft is made (see services/ai/safety.assess_risk).
"""
import os

from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.add_column("scheduled_posts", sa.Column("publishing_started_at", sa.DateTime(timezone=True)))
    op.add_column("scheduled_posts", sa.Column("first_attempt_at", sa.DateTime(timezone=True)))
    op.add_column("scheduled_posts", sa.Column("publish_token", sa.UUID()))
    op.create_index("uq_scheduled_posts_google_name", "scheduled_posts", ["google_location_id", "google_post_name"], unique=True,
                    postgresql_where=sa.text("google_post_name is not null"))
    op.create_index("ix_scheduled_posts_publishing", "scheduled_posts", ["status", "publishing_started_at"], postgresql_where=sa.text("status = 'publishing'"))

    op.add_column("tenants", sa.Column("ai_monthly_budget_usd", sa.Numeric(10, 4)))
    op.add_column("reply_drafts", sa.Column("risk_level", sa.String(8)))

    op.create_table(
        "ai_call_ledger",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=True),  # NULL = a platform-level call; deliberately no FK (see docstring)
        sa.Column("kind", sa.String(32), nullable=False),  # the task: reply_draft | post_draft | review_generate | ...
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(80)),
        sa.Column("input_tokens", sa.Integer()),  # as the provider reported them; NULL when it reported none
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("cost_usd", sa.Numeric(12, 6)),  # estimated from the configured prices (or the provider's own figure); NULL = unknown price
        sa.Column("status", sa.String(16), nullable=False),  # ok | error | blocked
        sa.Column("error_code", sa.String(32)),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status in ('ok','error','blocked')", name="ck_ai_call_status"),
    )
    op.create_index("ix_ai_call_ledger_created", "ai_call_ledger", ["created_at"])
    op.create_index("ix_ai_call_ledger_tenant_created", "ai_call_ledger", ["tenant_id", "created_at"])
    op.execute("ALTER TABLE ai_call_ledger ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ai_call_ledger FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON ai_call_ledger USING ({COND}) WITH CHECK ({COND})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT ON ai_call_ledger TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ai_call_ledger")
    op.drop_table("ai_call_ledger")
    op.drop_column("reply_drafts", "risk_level")
    op.drop_column("tenants", "ai_monthly_budget_usd")
    op.drop_index("ix_scheduled_posts_publishing", table_name="scheduled_posts")
    op.drop_index("uq_scheduled_posts_google_name", table_name="scheduled_posts")
    op.drop_column("scheduled_posts", "publish_token")
    op.drop_column("scheduled_posts", "first_attempt_at")
    op.drop_column("scheduled_posts", "publishing_started_at")
