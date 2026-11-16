"""Growth agent: knowledge base, agent tasks (state machine), scheduled posts, Google snapshots, health history, settings.

All tables are tenant-scoped with row-level security. Nothing here changes existing data. Additive and reversible.

Revision ID: 0017
Revises: 0016
"""
import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
TABLES = ("business_knowledge", "agent_settings", "agent_tasks", "agent_task_events", "agent_runs", "scheduled_posts", "gbp_snapshots", "health_snapshots")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def _id():
    return sa.Column("id", sa.UUID(), nullable=False)


def _tenant():
    return sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)


def _ts(name="created_at"):
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "business_knowledge", _id(), _tenant(),
        sa.Column("offers", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("hours", sa.Text()), sa.Column("brand_voice", sa.Text()),
        sa.Column("faqs", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("approved_claims", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("prohibited_claims", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("safety_profile", sa.String(16), nullable=False, server_default="general"),
        sa.Column("updated_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        _ts(), _ts("updated_at"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("tenant_id", name="uq_business_knowledge_tenant"))
    op.create_table(
        "agent_settings", _id(), _tenant(),
        sa.Column("daily_plan", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("auto_draft_replies", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_plan_date", sa.Date()),
        _ts(), _ts("updated_at"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("tenant_id", name="uq_agent_settings_tenant"))
    op.create_table(
        "agent_tasks", _id(), _tenant(),
        sa.Column("location_id", sa.UUID(), sa.ForeignKey("locations.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(32), nullable=False), sa.Column("title", sa.String(200), nullable=False),
        sa.Column("why", sa.Text(), nullable=False), sa.Column("evidence", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("suggested_action", sa.Text()),
        sa.Column("status", sa.String(20), nullable=False, server_default="suggested"),
        sa.Column("draft", postgresql.JSONB()),
        sa.Column("ref_type", sa.String(24)), sa.Column("ref_id", sa.UUID()),
        sa.Column("dedupe_key", sa.String(120), nullable=False),
        sa.Column("priority", sa.SmallInteger(), nullable=False, server_default="50"),
        sa.Column("plan_date", sa.Date(), nullable=False),
        sa.Column("snoozed_until", sa.DateTime(timezone=True)), sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("failure_reason", sa.Text()),
        _ts(), _ts("updated_at"), sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status in ('suggested','drafted','awaiting_approval','approved','scheduled','published','failed','snoozed','dismissed','done')", name="ck_agent_task_status"))
    op.create_index("ix_agent_tasks_tenant_status", "agent_tasks", ["tenant_id", "status"])
    op.create_index("uq_agent_tasks_open_dedupe", "agent_tasks", ["tenant_id", "dedupe_key"], unique=True,
                    postgresql_where=sa.text("status not in ('published','done','dismissed')"))
    op.create_table(
        "agent_task_events", _id(), _tenant(),
        sa.Column("task_id", sa.UUID(), sa.ForeignKey("agent_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", sa.String(20)), sa.Column("to_status", sa.String(20), nullable=False),
        sa.Column("actor", sa.String(16), nullable=False), sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("note", sa.Text()), _ts(), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_agent_task_events_task", "agent_task_events", ["task_id", "created_at"])
    op.create_table(
        "agent_runs", _id(), _tenant(),
        sa.Column("kind", sa.String(32), nullable=False), sa.Column("status", sa.String(12), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("detail", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("error", sa.Text()),
        sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_agent_runs_tenant_started", "agent_runs", ["tenant_id", "started_at"])
    op.create_table(
        "scheduled_posts", _id(), _tenant(),
        sa.Column("google_location_id", sa.UUID(), sa.ForeignKey("google_locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False), sa.Column("language", sa.String(8), nullable=False, server_default="en"),
        sa.Column("cta_type", sa.String(16)), sa.Column("cta_url", sa.String(500)), sa.Column("photo_url", sa.String(500)),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)), sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)), sa.Column("google_post_name", sa.String(300)),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"), sa.Column("failure_reason", sa.Text()),
        sa.Column("generated_by_ai", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL")), sa.Column("approved_at", sa.DateTime(timezone=True)),
        _ts(), _ts("updated_at"), sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status in ('draft','awaiting_approval','approved','scheduled','publishing','published','failed','canceled')", name="ck_scheduled_post_status"))
    op.create_index("ix_scheduled_posts_due", "scheduled_posts", ["status", "scheduled_for"])
    op.create_index("ix_scheduled_posts_tenant", "scheduled_posts", ["tenant_id", "status"])
    op.create_table(
        "gbp_snapshots", _id(), _tenant(),
        sa.Column("google_location_id", sa.UUID(), sa.ForeignKey("google_locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("info", postgresql.JSONB()), sa.Column("posts", postgresql.JSONB()), sa.Column("media", postgresql.JSONB()), sa.Column("performance", postgresql.JSONB()),
        sa.Column("fetched_at", sa.DateTime(timezone=True)), sa.Column("error", sa.Text()),
        _ts(), _ts("updated_at"), sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("google_location_id", name="uq_gbp_snapshot_location"))
    op.create_table(
        "health_snapshots", _id(), _tenant(),
        sa.Column("day", sa.Date(), nullable=False), sa.Column("score", sa.SmallInteger()),
        sa.Column("breakdown", postgresql.JSONB(), nullable=False), _ts(), sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "day", name="uq_health_snapshot_day"))

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
