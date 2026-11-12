"""Google's moderation state for owner replies (reviewReplyState / policyViolation on ReviewReply).

A 200 from reviews.updateReply means Google stored the reply, not that it is public: it can be PENDING or REJECTED.
Storing the state lets FlowQR stop reporting a rejected reply as published. Additive and reversible.

Revision ID: 0012
Revises: 0011
"""
from alembic import op
import sqlalchemy as sa

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reviews", sa.Column("google_reply_state", sa.String(16), nullable=True))
    op.add_column("reviews", sa.Column("google_reply_policy_violation", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("reviews", "google_reply_policy_violation")
    op.drop_column("reviews", "google_reply_state")
