"""Review drafts: how many AI-written versions a customer visit has received.

Revision ID: 0069
Revises: 0068

Additive: one small column with a default of 0 on review_drafts (a table that already has forced row-level security, so the policy is unchanged). Existing rows read 0, which only means
"this visit has not used its two AI-written versions yet". Nothing is rewritten.
"""
import sqlalchemy as sa
from alembic import op

revision = "0069"
down_revision = "0068"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("review_drafts", sa.Column("ai_writes", sa.SmallInteger(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("review_drafts", "ai_writes")
