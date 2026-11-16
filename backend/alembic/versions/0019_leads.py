"""Demo requests from the public marketing site (leads). Not tenant-scoped, so no RLS policy; the app role may only insert and read.

Revision ID: 0019
Revises: 0018
"""
import os

from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")


def upgrade() -> None:
    op.create_table(
        "leads",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("business_name", sa.String(160), nullable=False),
        sa.Column("city", sa.String(80), nullable=False),
        sa.Column("business_type", sa.String(40), nullable=False),
        sa.Column("locations", sa.SmallInteger(), nullable=False),
        sa.Column("phone", sa.String(16), nullable=False),
        sa.Column("whatsapp_ok", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("preferred_time", sa.String(40)),
        sa.Column("source", sa.String(40), nullable=False, server_default="demo"),
        sa.Column("ip_hash", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_leads_created", "leads", ["created_at"])
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT ON leads TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_index("ix_leads_created", table_name="leads")
    op.drop_table("leads")
