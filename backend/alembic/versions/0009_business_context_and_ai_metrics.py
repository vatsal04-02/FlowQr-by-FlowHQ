"""Business context (tenants.review_context), per-suggestion analytics (review_events.suggestion_id) and richer AI cost metrics.

Additive and reversible: every new column is nullable or has a default, so existing rows and the running app are unaffected.
No personal data is added: suggestion ids are catalog topic ids ("staff", "food"), and the AI metrics are numbers.

Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("review_context", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("review_events", sa.Column("suggestion_id", sa.String(length=40), nullable=True))
    op.create_index("ix_review_events_tenant_suggestion", "review_events", ["tenant_id", "suggestion_id"], postgresql_where=sa.text("suggestion_id IS NOT NULL"))
    for name in ("model_calls", "attempts", "rejects_rules", "rejects_factcheck"):
        op.add_column("ai_generation_logs", sa.Column(name, sa.Integer(), nullable=True))
    op.add_column("ai_generation_logs", sa.Column("cost_usd", sa.Numeric(precision=10, scale=6), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_generation_logs", "cost_usd")
    for name in ("rejects_factcheck", "rejects_rules", "attempts", "model_calls"):
        op.drop_column("ai_generation_logs", name)
    op.drop_index("ix_review_events_tenant_suggestion", table_name="review_events")
    op.drop_column("review_events", "suggestion_id")
    op.drop_column("tenants", "review_context")
