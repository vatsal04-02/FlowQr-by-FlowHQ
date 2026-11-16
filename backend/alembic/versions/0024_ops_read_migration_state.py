"""Let the app role READ (never write) the migration version, so the admin Operations page can prove the database matches the code.

Revision ID: 0024
Revises: 0023
"""
import os

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")


def upgrade() -> None:
    op.execute(f"""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT ON alembic_version TO {APP_ROLE}';
        END IF;
    END $$""")


def downgrade() -> None:
    op.execute(f"""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'REVOKE SELECT ON alembic_version FROM {APP_ROLE}';
        END IF;
    END $$""")
