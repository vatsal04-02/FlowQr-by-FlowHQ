"""Record provider-reported token usage on AI generation logs (nullable; existing rows are untouched).

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_generation_logs", sa.Column("prompt_tokens", sa.Integer(), nullable=True))
    op.add_column("ai_generation_logs", sa.Column("completion_tokens", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_generation_logs", "completion_tokens")
    op.drop_column("ai_generation_logs", "prompt_tokens")
