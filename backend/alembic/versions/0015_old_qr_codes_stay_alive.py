"""Earlier QR codes of a campaign keep working as aliases.

Issuing a new code for a campaign no longer kills the printed copies of the old one: every id in
review_campaign_retired_ids resolves to its campaign unless it was deliberately deactivated (deactivated_at set).
Rows written under 0014 (when a replaced code stopped working) become working aliases again.
Additive and reversible.

Revision ID: 0015
Revises: 0014
"""
from alembic import op
import sqlalchemy as sa

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("review_campaign_retired_ids", sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("review_campaign_retired_ids", "deactivated_at")
