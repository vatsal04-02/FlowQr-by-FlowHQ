"""Pre-printed card inventory: lifecycle states, campaign binding, QR/NFC channel.

* card_status gains 'generated', 'reserved', 'archived', 'retired' (the existing values stay valid and keep their meaning)
* qr_cards.campaign_id       the review campaign a card opens (NULL = the plain card landing page, exactly as before)
* qr_cards.qr_path           'c' for every card that already exists (its printed QR encodes /c/<token> and must keep doing so);
                             new cards use 'q'. The NFC address /n/<token> works for every card, old and new.
* qr_cards.retired_at        when a card was permanently retired
* card_batches.released_at   when the batch was marked printed/in stock (generated -> unassigned)
* card_assignments.campaign_id / ended_reason   what a card pointed at, and why that period ended
* scan_events.channel        'qr' or 'nfc'. NULL for every event recorded before this migration (the channel was not known).

No token, card code or existing row's meaning is changed. Additive. Downgrade drops the new columns and maps the new states back
to the nearest old one (retired/archived -> deactivated, generated/reserved -> unassigned) because PostgreSQL cannot drop enum values.

Revision ID: 0018
Revises: 0017
"""
from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():  # ADD VALUE must be committed before the value can be used
        for v in ("generated", "reserved", "archived", "retired"):
            op.execute(f"ALTER TYPE card_status ADD VALUE IF NOT EXISTS '{v}'")

    op.add_column("qr_cards", sa.Column("campaign_id", sa.UUID(), nullable=True))
    op.create_foreign_key("fk_qr_cards_campaign", "qr_cards", "review_campaigns", ["campaign_id"], ["id"], ondelete="SET NULL")
    op.add_column("qr_cards", sa.Column("qr_path", sa.String(1), nullable=False, server_default="c"))
    op.add_column("qr_cards", sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_qr_cards_campaign", "qr_cards", ["campaign_id"])

    op.add_column("card_batches", sa.Column("released_at", sa.DateTime(timezone=True), nullable=True))
    # Batches that already exist were printed long ago.
    op.execute("UPDATE card_batches SET released_at = created_at WHERE released_at IS NULL")

    op.add_column("card_assignments", sa.Column("campaign_id", sa.UUID(), nullable=True))
    op.create_foreign_key("fk_card_assignments_campaign", "card_assignments", "review_campaigns", ["campaign_id"], ["id"], ondelete="SET NULL")
    op.add_column("card_assignments", sa.Column("ended_reason", sa.String(24), nullable=True))

    op.add_column("scan_events", sa.Column("channel", sa.String(8), nullable=True))
    op.create_check_constraint("ck_scan_events_channel", "scan_events", "channel IS NULL OR channel IN ('qr','nfc')")
    op.create_index("ix_scan_events_card_channel", "scan_events", ["card_id", "channel"])


def downgrade() -> None:
    op.drop_index("ix_scan_events_card_channel", table_name="scan_events")
    op.drop_constraint("ck_scan_events_channel", "scan_events", type_="check")
    op.drop_column("scan_events", "channel")
    op.drop_column("card_assignments", "ended_reason")
    op.drop_constraint("fk_card_assignments_campaign", "card_assignments", type_="foreignkey")
    op.drop_column("card_assignments", "campaign_id")
    op.drop_column("card_batches", "released_at")
    op.drop_index("ix_qr_cards_campaign", table_name="qr_cards")
    # Map the new states back before the columns that explain them go away.
    op.execute("UPDATE qr_cards SET status = 'deactivated' WHERE status::text IN ('retired','archived')")
    op.execute("UPDATE qr_cards SET status = 'unassigned', tenant_id = NULL, location_id = NULL WHERE status::text IN ('generated','reserved')")
    op.drop_column("qr_cards", "retired_at")
    op.drop_column("qr_cards", "qr_path")
    op.drop_constraint("fk_qr_cards_campaign", "qr_cards", type_="foreignkey")
    op.drop_column("qr_cards", "campaign_id")
