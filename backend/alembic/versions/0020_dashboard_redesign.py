"""Dashboard redesign (PRD §9): a monthly review goal per business, and per-member notification preferences + bell read state.

Revision ID: 0020
Revises: 0019
"""
import os

from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.add_column("tenants", sa.Column("review_goal", sa.Integer()))
    op.create_table(
        "notification_prefs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.UUID(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email_new_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("email_flagged_review", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("email_sync_failed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("email_trial_ending", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("bell_seen_at", sa.DateTime(timezone=True)),
        sa.Column("last_emailed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_notification_prefs_member"),
    )
    op.execute("ALTER TABLE notification_prefs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE notification_prefs FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON notification_prefs USING ({COND}) WITH CHECK ({COND})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON notification_prefs TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON notification_prefs")
    op.drop_table("notification_prefs")
    op.drop_column("tenants", "review_goal")
