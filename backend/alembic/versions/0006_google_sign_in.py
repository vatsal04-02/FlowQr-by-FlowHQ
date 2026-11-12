"""Sign in with Google: users.google_sub (unique, nullable) and a nullable users.password_hash.

Existing rows are untouched (google_sub stays NULL, every current password hash stays valid) and no session
is affected. Downgrade is reversible: Google-only accounts (NULL hash) get the unusable placeholder '!' so the
NOT NULL constraint can return; '!' never verifies as an Argon2 hash, so those users can still get in through
"Forgot password". The google_sub column (and therefore the Google links) is dropped.

Revision ID: 0006
Revises: 0005
"""
from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("google_sub", sa.String(length=255), nullable=True))
    op.create_unique_constraint("uq_users_google_sub", "users", ["google_sub"])
    op.alter_column("users", "password_hash", existing_type=sa.String(length=255), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE users SET password_hash = '!' WHERE password_hash IS NULL")
    op.alter_column("users", "password_hash", existing_type=sa.String(length=255), nullable=False)
    op.drop_constraint("uq_users_google_sub", "users", type_="unique")
    op.drop_column("users", "google_sub")
