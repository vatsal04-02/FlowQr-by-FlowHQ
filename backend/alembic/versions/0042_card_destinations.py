"""QR/NFC asset management: per-card destination override with history, NFC programming status, richer scan events.

Revision ID: 0042
Revises: 0041

Additive only. Nothing about an existing card changes: `destination_url` is NULL (= today's behaviour, the review landing page), `nfc_programmed_at` is NULL (= not marked programmed).
* qr_cards: destination_url, destination_set_at (what a card sends visitors to INSTEAD of its landing page, when set), nfc_programmed_at / nfc_programmed_by (an admin's statement that the tag was written: FlowQR cannot
  write tags itself).
* card_destination_history: append-only record of every set/clear (old and new URL, who, why, when). The app role can SELECT and INSERT, never UPDATE or DELETE.
* scan_events: referrer_host (host only, never a path or query), device (mobile|tablet|desktop|other), placement (the card's label at the time), campaign_id (the card's campaign at the time).
Numbering: sits on 0041. 0038 (consent) and 0039 (trial) are on other unreleased branches; whoever lands second changes one `down_revision` line.
"""
import os

import sqlalchemy as sa
from alembic import op

revision = "0042"
down_revision = "0041"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.add_column("qr_cards", sa.Column("destination_url", sa.String(2000)))
    op.add_column("qr_cards", sa.Column("destination_set_at", sa.DateTime(timezone=True)))
    op.add_column("qr_cards", sa.Column("nfc_programmed_at", sa.DateTime(timezone=True)))
    op.add_column("qr_cards", sa.Column("nfc_programmed_by", sa.UUID()))
    op.create_foreign_key("fk_qr_cards_nfc_programmed_by", "qr_cards", "users", ["nfc_programmed_by"], ["id"], ondelete="SET NULL")

    op.create_table(
        "card_destination_history",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("card_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID()),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("old_url", sa.String(2000)),
        sa.Column("new_url", sa.String(2000)),
        sa.Column("reason", sa.String(300)),
        sa.Column("changed_by", sa.UUID()),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["card_id"], ["qr_cards.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint("action in ('set', 'cleared')", name="ck_card_destination_action"),
    )
    op.create_index("ix_card_destination_history_card", "card_destination_history", ["card_id", "changed_at"])
    op.execute("ALTER TABLE card_destination_history ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE card_destination_history FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON card_destination_history USING ({COND}) WITH CHECK ({COND})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT ON card_destination_history TO {APP_ROLE}';
          END IF;
        END $$;
    """)

    op.add_column("scan_events", sa.Column("referrer_host", sa.String(120)))
    op.add_column("scan_events", sa.Column("device", sa.String(8)))
    op.add_column("scan_events", sa.Column("placement", sa.String(120)))
    op.add_column("scan_events", sa.Column("campaign_id", sa.UUID()))
    op.create_foreign_key("fk_scan_events_campaign", "scan_events", "review_campaigns", ["campaign_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    op.drop_constraint("fk_scan_events_campaign", "scan_events", type_="foreignkey")
    for c in ("campaign_id", "placement", "device", "referrer_host"):
        op.drop_column("scan_events", c)
    op.drop_table("card_destination_history")
    op.drop_constraint("fk_qr_cards_nfc_programmed_by", "qr_cards", type_="foreignkey")
    for c in ("nfc_programmed_by", "nfc_programmed_at", "destination_set_at", "destination_url"):
        op.drop_column("qr_cards", c)
