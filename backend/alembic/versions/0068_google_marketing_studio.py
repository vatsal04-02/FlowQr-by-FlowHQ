"""Google Marketing Studio: campaigns, the media/document library, and the campaign link on scheduled posts.

Revision ID: 0068
Revises: 0067

Additive. Nothing existing is rewritten and nothing is switched on. Posts stay in scheduled_posts (so approval, scheduling, retries and the governed publisher are unchanged);
they gain campaign_id, asset_id, keywords and suggested_for, all nullable. Forced row-level security with the usual tenant policy on both new tables.
"""
import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0068"
down_revision = "0067"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
TABLES = ("marketing_campaigns", "marketing_assets")


def _ts():
    return [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade() -> None:
    op.create_table(
        "marketing_campaigns",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("google_location_id", sa.UUID(), nullable=False),
        sa.Column("title", sa.String(120), nullable=False), sa.Column("brief", sa.Text(), nullable=False), sa.Column("objective", sa.String(16), nullable=False),
        sa.Column("duration_days", sa.SmallInteger(), nullable=False), sa.Column("start_date", sa.Date(), nullable=False), sa.Column("language", sa.String(8), nullable=False, server_default="en"),
        sa.Column("status", sa.String(16), nullable=False, server_default="generating"),
        sa.Column("event_title", sa.String(58)), sa.Column("event_start", sa.DateTime(timezone=True)), sa.Column("event_end", sa.DateTime(timezone=True)),
        sa.Column("asset_ids", postgresql.JSONB(), nullable=False, server_default="[]"), sa.Column("notes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("keywords", postgresql.JSONB(), nullable=False, server_default="[]"), sa.Column("created_by", sa.UUID()),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["google_location_id"], ["google_locations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint("objective in ('keep_active','products','offers','enquiries','events','awareness')", name="ck_marketing_campaign_objective"),
        sa.CheckConstraint("duration_days in (7,15,30)", name="ck_marketing_campaign_duration"),
        sa.CheckConstraint("status in ('generating','ready','failed','archived')", name="ck_marketing_campaign_status"),
    )
    op.create_index("ix_marketing_campaigns_tenant", "marketing_campaigns", ["tenant_id", "created_at"])
    op.create_table(
        "marketing_assets",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("file_name", sa.String(200)), sa.Column("label", sa.String(200)), sa.Column("content_type", sa.String(80), nullable=False), sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer()), sa.Column("height", sa.Integer()), sa.Column("sha256", sa.String(64), nullable=False), sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("text_excerpt", sa.Text()), sa.Column("public_token", sa.String(48)), sa.Column("created_by", sa.UUID()),
        *_ts(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint("kind in ('image','document')", name="ck_marketing_asset_kind"),
    )
    op.create_index("ix_marketing_assets_tenant", "marketing_assets", ["tenant_id", "created_at"])
    op.create_index("ix_marketing_assets_token", "marketing_assets", ["public_token"], unique=True)

    op.add_column("scheduled_posts", sa.Column("campaign_id", sa.UUID(), nullable=True))
    op.add_column("scheduled_posts", sa.Column("asset_id", sa.UUID(), nullable=True))
    op.add_column("scheduled_posts", sa.Column("keywords", postgresql.JSONB(), nullable=True))
    op.add_column("scheduled_posts", sa.Column("suggested_for", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_scheduled_posts_campaign", "scheduled_posts", "marketing_campaigns", ["campaign_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_scheduled_posts_asset", "scheduled_posts", "marketing_assets", ["asset_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_scheduled_posts_campaign", "scheduled_posts", ["campaign_id"])

    for t in TABLES:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({COND}) WITH CHECK ({COND})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON {", ".join(TABLES)} TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_index("ix_scheduled_posts_campaign", "scheduled_posts")
    op.drop_constraint("fk_scheduled_posts_asset", "scheduled_posts", type_="foreignkey")
    op.drop_constraint("fk_scheduled_posts_campaign", "scheduled_posts", type_="foreignkey")
    for c in ("suggested_for", "keywords", "asset_id", "campaign_id"):
        op.drop_column("scheduled_posts", c)
    op.drop_table("marketing_assets")
    op.drop_table("marketing_campaigns")
