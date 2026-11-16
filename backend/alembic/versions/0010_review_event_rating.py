"""Star rating on review events, so the rating distribution survives the retention purge.

The customer's 1-5 rating is kept on the session (deleted with the customer's words after the retention period) and, as a bare number, on the
`feedback_submitted` event (kept, like every other event, because it holds no text). It is the rating the customer chose on the FlowQR page, not a
Google rating, and it is never used to hide, route or restrict anything. Additive and reversible; no personal data.

Revision ID: 0010
Revises: 0009
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("review_events", sa.Column("rating", sa.SmallInteger(), nullable=True))
    op.create_check_constraint("ck_review_events_rating", "review_events", "rating IS NULL OR rating BETWEEN 1 AND 5")


def downgrade() -> None:
    op.drop_constraint("ck_review_events_rating", "review_events", type_="check")
    op.drop_column("review_events", "rating")
