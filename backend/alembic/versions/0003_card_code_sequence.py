"""Sequence for human-readable card codes (FQR-0001 ...).

Revision ID: 0003
Revises: 0002
"""
import os

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")


def upgrade() -> None:
    op.execute("CREATE SEQUENCE card_code_seq START 1")
    op.execute(
        f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE card_code_seq TO {APP_ROLE}';
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("DROP SEQUENCE IF EXISTS card_code_seq")
