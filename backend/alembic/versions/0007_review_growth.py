"""Review Growth: QR campaigns, anonymous review sessions, AI drafts, funnel events (all tenant-RLS protected).

Purely additive: no existing table or row is touched. Downgrade drops the four new tables (and their data).

Revision ID: 0007
Revises: 0006
"""
import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
TABLES = ("review_campaigns", "review_sessions", "review_drafts", "review_events")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def _ts(name="created_at", nullable=False, default=True):
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.text("now()") if default else None, nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "review_campaigns",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("location_id", sa.UUID(), nullable=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("public_id", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="active"),
        sa.Column("customization", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("qr_rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.UUID(), nullable=True),
        _ts("created_at"), _ts("updated_at"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["location_id"], ["locations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_review_campaigns_public_id"),
        sa.CheckConstraint("status in ('active','paused','archived')", name="ck_review_campaign_status"),
    )
    op.create_index("ix_review_campaigns_tenant", "review_campaigns", ["tenant_id", "status"])

    op.create_table(
        "review_sessions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("session_identifier", sa.String(length=32), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=False, server_default="en"),
        sa.Column("style", sa.String(length=16), nullable=False, server_default="natural"),
        sa.Column("customer_input", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("rating", sa.SmallInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["review_campaigns.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_identifier", name="uq_review_sessions_identifier"),
        sa.CheckConstraint("rating is null or (rating between 1 and 5)", name="ck_review_session_rating"),
    )
    op.create_index("ix_review_sessions_campaign_created", "review_sessions", ["campaign_id", "created_at"])
    op.create_index("ix_review_sessions_created", "review_sessions", ["created_at"])

    op.create_table(
        "review_drafts",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=False),
        sa.Column("generated_content", sa.Text(), nullable=True),
        sa.Column("final_content", sa.Text(), nullable=True),
        sa.Column("generation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ai_assisted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        _ts("created_at"), _ts("updated_at"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["review_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", name="uq_review_drafts_session"),
    )

    op.create_table(
        "review_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(length=24), nullable=False),
        sa.Column("visitor_hash", sa.String(length=64), nullable=True),
        sa.Column("is_bot", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["review_campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["review_sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_events_tenant_created", "review_events", ["tenant_id", "created_at"])
    op.create_index("ix_review_events_campaign_type_created", "review_events", ["campaign_id", "event_type", "created_at"])

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
    op.drop_index("ix_review_events_campaign_type_created", table_name="review_events")
    op.drop_index("ix_review_events_tenant_created", table_name="review_events")
    op.drop_table("review_events")
    op.drop_table("review_drafts")
    op.drop_index("ix_review_sessions_created", table_name="review_sessions")
    op.drop_index("ix_review_sessions_campaign_created", table_name="review_sessions")
    op.drop_table("review_sessions")
    op.drop_index("ix_review_campaigns_tenant", table_name="review_campaigns")
    op.drop_table("review_campaigns")
