"""Card on file for the free trial.

Revision ID: 0033
Revises: 0032

Owner decision 2026-11-15: the free trial needs a card. `subscriptions.card_status` records it per business: NULL = no card needed (every business that already exists,
and every trial while TRIAL_REQUIRES_CARD is off), "required" = a new trial that stays locked until the owner authorises a card, "on_file" = authorised (the first charge
is scheduled for the day the trial ends). Additive and nullable: nothing existing changes. Downgrade drops the column.
"""
from alembic import op
import sqlalchemy as sa

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("subscriptions", sa.Column("card_status", sa.String(12), nullable=True))


def downgrade() -> None:
    op.drop_column("subscriptions", "card_status")
