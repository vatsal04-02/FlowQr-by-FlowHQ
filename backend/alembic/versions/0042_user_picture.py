"""The person's Google account photo, shown as their avatar in the app.

Revision ID: 0042
Revises: 0041

One nullable column on `users`: the https URL of the profile picture that Google puts in the sign-in token (the `picture` claim, part of the `profile` scope the sign-in already asks for).
Only a link is kept, never the image, and only a Google-hosted one (services/google/login.py `safe_picture`). It is refreshed on every Google sign-in, so a changed photo follows the person.
Additive only: no existing row changes (every user starts with NULL and the app falls back to their initials). Downgrade drops the column.

Numbering: 0040 and 0041 (prepaid) sit underneath on the release line; 0038 (consent) and 0039 (trial) are on other unreleased branches. Whoever lands second changes one `down_revision` line.
"""
import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("picture_url", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "picture_url")
