"""Review drafts: the 2-3 suggestions a customer was shown in one round.

Revision ID: 0072
Revises: 0071

Additive: one nullable JSONB column on review_drafts (a table that already has forced row-level security, so the policy is unchanged). Existing rows stay NULL, which the app reads as "one
suggestion: generated_content". The list holds only AI-written text built from stars and chosen keywords (or the customer's own words for that visit, which the existing retention purge deletes
with the draft). Reversible: the downgrade drops the column.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0072"
down_revision = "0071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("review_drafts", sa.Column("suggestions", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("review_drafts", "suggestions")
