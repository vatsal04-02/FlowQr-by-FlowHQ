"""Self-service agency onboarding: the action categories the client agreed to, a once-only log of the e-mails sent to the client, and when the first agency sync was queued.

Revision ID: 0066
Revises: 0065

Additive and nullable/defaulted: nothing existing changes, no row is rewritten, and an authorization recorded before this migration keeps `consent_actions` NULL, which means "agreed to the wording of
the time" (it covered reading reviews, replying, posting and profile updates, each still needing the client's approval). Row-level security and grants of google_agency_authorizations are unchanged.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("google_agency_authorizations", sa.Column("consent_actions", postgresql.JSONB(), nullable=True))
    op.add_column("google_agency_authorizations", sa.Column("notices_sent", postgresql.JSONB(), server_default="{}", nullable=False))
    op.add_column("google_agency_authorizations", sa.Column("initial_sync_enqueued_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("google_agency_authorizations", "initial_sync_enqueued_at")
    op.drop_column("google_agency_authorizations", "notices_sent")
    op.drop_column("google_agency_authorizations", "consent_actions")
