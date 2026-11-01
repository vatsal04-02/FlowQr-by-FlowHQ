"""Record the card base URL used when each batch was generated (so a later domain change can't silently strand printed cards).

Revision ID: 0005
Revises: 0004
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("card_batches", sa.Column("base_url", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("card_batches", "base_url")
