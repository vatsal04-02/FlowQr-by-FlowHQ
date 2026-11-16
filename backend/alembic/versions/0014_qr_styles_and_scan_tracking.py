"""QR customisation, pause, retired-code history and a location snapshot on campaign scans.

* qr_styles                      one brand style (+ optional logo) per tenant
* review_campaigns.qr_style      optional per-campaign override of that style
* card_status 'paused'           a card can be paused and resumed without being retired
* review_campaign_retired_ids    every public id a campaign ever had, so a replaced code is recognised (410) and never reissued
* review_events.location_id      where the campaign pointed when the event happened (survives re-pointing the campaign)

No existing token, public id or card code is touched: printed codes keep resolving exactly as before.
Additive. Downgrade removes everything except the 'paused' enum value (PostgreSQL cannot drop an enum value); paused
cards are set back to 'deactivated' first.

Revision ID: 0014
Revises: 0013
"""
import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
TABLES = ("qr_styles", "review_campaign_retired_ids")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    with op.get_context().autocommit_block():  # ADD VALUE must be committed before the value can be used
        op.execute("ALTER TYPE card_status ADD VALUE IF NOT EXISTS 'paused'")

    op.create_table(
        "qr_styles",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("style", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("logo_png", sa.LargeBinary(), nullable=True),
        sa.Column("updated_by", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_qr_styles_tenant"),
    )
    op.create_table(
        "review_campaign_retired_ids",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("campaign_id", sa.UUID(), nullable=False),
        sa.Column("public_id", sa.String(32), nullable=False),
        sa.Column("retired_by", sa.UUID(), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["review_campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["retired_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("public_id", name="uq_retired_public_id"),
    )
    op.create_index("ix_review_campaign_retired_ids_campaign_id", "review_campaign_retired_ids", ["campaign_id"])
    op.add_column("review_campaigns", sa.Column("qr_style", postgresql.JSONB(), nullable=True))
    op.add_column("review_events", sa.Column("location_id", sa.UUID(), nullable=True))
    op.create_foreign_key("fk_review_events_location", "review_events", "locations", ["location_id"], ["id"], ondelete="SET NULL")
    # Best-effort backfill: older events get the campaign's CURRENT location (the location at event time was never recorded).
    op.execute("UPDATE review_events e SET location_id = c.location_id FROM review_campaigns c WHERE c.id = e.campaign_id AND e.location_id IS NULL")

    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({COND}) WITH CHECK ({COND})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON {", ".join(TABLES)} TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute("UPDATE qr_cards SET status = 'deactivated' WHERE status::text = 'paused'")
    for table in TABLES:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.drop_constraint("fk_review_events_location", "review_events", type_="foreignkey")
    op.drop_column("review_events", "location_id")
    op.drop_column("review_campaigns", "qr_style")
    op.drop_table("review_campaign_retired_ids")
    op.drop_table("qr_styles")
