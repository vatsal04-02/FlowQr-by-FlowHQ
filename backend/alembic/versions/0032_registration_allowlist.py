"""Registration gate: the list of email addresses that may create an account while registration is in `allowlist` mode.

Revision ID: 0032
Revises: 0031

Owner decision 2026-11-15: production registration is `allowlist` by default (see services/registration.py). This is the platform-level list managed by a platform admin (Admin API, or
`python -m app.cli registration`); the environment variable REGISTRATION_ALLOWLIST can add more addresses. Not tenant-scoped (it exists before any business does), so no row-level security;
the application role may SELECT, INSERT, UPDATE and DELETE it. Addresses are stored already normalised (lower case, trimmed). Additive: nothing existing is changed.
"""
import os

from alembic import op
import sqlalchemy as sa

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")


def upgrade() -> None:
    op.create_table(
        "registration_allowlist",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("note", sa.String(300)),
        sa.Column("added_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("used_at", sa.DateTime(timezone=True)),  # when an account was created with this address
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_registration_allowlist_email"),
    )
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON registration_allowlist TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_table("registration_allowlist")
