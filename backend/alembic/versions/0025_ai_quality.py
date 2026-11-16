"""AI output tracking (acceptance rate, edit distance, regenerations) and the business's target audience.

Revision ID: 0025
Revises: 0024
"""
import os

from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.add_column("business_knowledge", sa.Column("audience", sa.Text()))
    op.create_table(
        "ai_outputs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),  # reply | post | description
        sa.Column("ref_id", sa.UUID(), nullable=False),  # reply_drafts.id | scheduled_posts.id | agent_tasks.id
        sa.Column("model", sa.String(80)),
        sa.Column("language", sa.String(8)),
        sa.Column("original_text", sa.Text(), nullable=False),  # the AI's words, owner-facing business content (never customer review text)
        sa.Column("quality_score", sa.Float()),  # services/ai/quality.py score at generation time
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decision", sa.String(12)),  # approved | rejected | replaced
        sa.Column("edit_ratio", sa.Float()),  # 0 = published exactly as written, 1 = completely rewritten
        sa.Column("reject_reason", sa.String(40)),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("kind in ('reply','post','description')", name="ck_ai_output_kind"),
        sa.CheckConstraint("decision is null or decision in ('approved','rejected','replaced')", name="ck_ai_output_decision"),
        sa.UniqueConstraint("kind", "ref_id", name="uq_ai_output_ref"),
    )
    op.create_index("ix_ai_outputs_tenant_kind", "ai_outputs", ["tenant_id", "kind", "created_at"])
    op.execute("ALTER TABLE ai_outputs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE ai_outputs FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON ai_outputs USING ({COND}) WITH CHECK ({COND})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ai_outputs TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON ai_outputs")
    op.drop_table("ai_outputs")
    op.drop_column("business_knowledge", "audience")
