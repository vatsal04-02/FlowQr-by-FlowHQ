"""Account lifecycle: scheduled deletion (with a grace period the owner can cancel).

tenants.deletion_requested_at / deletion_scheduled_for. Nothing is deleted by this migration. Additive and reversible.

Revision ID: 0016
Revises: 0015
"""
from alembic import op
import sqlalchemy as sa

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tenants", sa.Column("deletion_scheduled_for", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tenants", "deletion_scheduled_for")
    op.drop_column("tenants", "deletion_requested_at")
