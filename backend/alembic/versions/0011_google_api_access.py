"""Track whether Google has approved the project for the Business Profile APIs, per connection.

Learned from real API responses (quota 0 / project-level 403), never assumed from a successful OAuth login. Additive and reversible.

Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("google_connections", sa.Column("api_access", sa.String(24), nullable=False, server_default="unknown"))
    op.add_column("google_connections", sa.Column("api_access_checked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("google_connections", "api_access_checked_at")
    op.drop_column("google_connections", "api_access")
