"""Google Business AI agent: photo library + scheduler, offer/event posts, a visible 'publishing' reply state, review request templates.

Revision ID: 0021
Revises: 0020
"""
import os

from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
TABLES = ("scheduled_media", "review_request_templates")


def _ts(name="created_at"):
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False)


def upgrade() -> None:
    # A new enum value may be added inside a transaction (PostgreSQL 12+); it is only used by later transactions.
    op.execute("ALTER TYPE reply_status ADD VALUE IF NOT EXISTS 'publishing' BEFORE 'published'")

    op.add_column("scheduled_posts", sa.Column("topic_type", sa.String(16), nullable=False, server_default="STANDARD"))
    op.add_column("scheduled_posts", sa.Column("event_title", sa.String(58)))
    op.add_column("scheduled_posts", sa.Column("event_start", sa.DateTime(timezone=True)))
    op.add_column("scheduled_posts", sa.Column("event_end", sa.DateTime(timezone=True)))
    op.add_column("scheduled_posts", sa.Column("offer_coupon", sa.String(58)))
    op.add_column("scheduled_posts", sa.Column("offer_url", sa.String(500)))
    op.add_column("scheduled_posts", sa.Column("offer_terms", sa.Text()))
    op.add_column("scheduled_posts", sa.Column("visual_hint", sa.Text()))
    op.create_check_constraint("ck_scheduled_post_topic", "scheduled_posts", "topic_type in ('STANDARD','OFFER','EVENT')")

    op.create_table(
        "scheduled_media",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("google_location_id", sa.UUID(), sa.ForeignKey("google_locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("description", sa.String(300)),
        sa.Column("file_name", sa.String(200)),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="awaiting_approval"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("failure_reason", sa.Text()),
        sa.Column("google_media_name", sa.String(300)),
        sa.Column("google_url", sa.String(1000)),
        sa.Column("google_checked_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        _ts(), _ts("updated_at"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status in ('awaiting_approval','scheduled','publishing','published','failed','canceled')", name="ck_scheduled_media_status"),
    )
    op.create_index("ix_scheduled_media_due", "scheduled_media", ["status", "scheduled_for"])
    op.create_index("ix_scheduled_media_tenant", "scheduled_media", ["tenant_id", "status"])

    op.create_table(
        "review_request_templates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False, server_default="whatsapp"),
        sa.Column("language", sa.String(8), nullable=False, server_default="en"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        _ts(), _ts("updated_at"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_request_templates_tenant_id", "review_request_templates", ["tenant_id"])

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
    op.drop_constraint("ck_scheduled_post_topic", "scheduled_posts")
    for c in ("visual_hint", "offer_terms", "offer_url", "offer_coupon", "event_end", "event_start", "event_title", "topic_type"):
        op.drop_column("scheduled_posts", c)
    # PostgreSQL cannot drop an enum value; 'publishing' stays (unused) after a downgrade.
