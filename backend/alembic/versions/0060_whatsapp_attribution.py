"""WhatsApp click-to-WhatsApp attribution and the free entry-point window (Phase 11).

Revision ID: 0060
Revises: 0059

Additive only. Production must be at 0059 first. Nothing here is on: the platform switch WHATSAPP_ATTRIBUTION_ENABLED is off, and attribution is part of the Pro tier only.

* whatsapp_conversations      + the ad/post a conversation came from (type, id, headline, link, click id) and when the entry point was last used.
* whatsapp_entry_windows      GLOBAL, dated, append-only: how long the free window after an ad or page-button click lasts. Sources disagree (72 hours, or 7 days from 21 Sep 2026), so BOTH are seeded
                              as UNVERIFIED and nothing is counted as free until an administrator has checked one against Meta's own documentation. A change is a new row with a new date.
* whatsapp_entry_window_checks append-only record of those checks, like whatsapp_rate_verifications.
"""
import os
import uuid
from datetime import date

import sqlalchemy as sa
from alembic import op

revision = "0060"
down_revision = "0059"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")


def upgrade() -> None:
    for name, col in (("referral_type", sa.String(8)), ("referral_id", sa.String(64)), ("referral_headline", sa.String(120)), ("referral_url", sa.String(300)), ("referral_clid", sa.String(200)),
                      ("entry_point_at", sa.DateTime(timezone=True))):
        op.add_column("whatsapp_conversations", sa.Column(name, col))
    op.create_table(
        "whatsapp_entry_windows",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("hours", sa.Integer(), nullable=False), sa.Column("effective_from", sa.Date(), nullable=False), sa.Column("source", sa.String(300), nullable=False),
        sa.Column("created_by", sa.UUID()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"), sa.UniqueConstraint("effective_from", name="uq_wa_entry_window_date"),
        sa.CheckConstraint("hours BETWEEN 1 AND 720", name="ck_wa_entry_window_hours"),
    )
    op.create_table(
        "whatsapp_entry_window_checks",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("window_id", sa.UUID(), nullable=False), sa.Column("verified", sa.Boolean(), nullable=False), sa.Column("note", sa.String(300), nullable=False),
        sa.Column("checked_by", sa.UUID()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["window_id"], ["whatsapp_entry_windows.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["checked_by"], ["users.id"], ondelete="SET NULL"),
    )
    windows = sa.table("whatsapp_entry_windows", sa.column("id", sa.UUID()), sa.column("hours", sa.Integer()), sa.column("effective_from", sa.Date()), sa.column("source", sa.String()))
    op.bulk_insert(windows, [
        {"id": uuid.uuid4(), "hours": 72, "effective_from": date(2026, 1, 1), "source": "Reported as 72 hours by third-party pages. NOT checked against Meta's documentation."},
        {"id": uuid.uuid4(), "hours": 168, "effective_from": date(2026, 9, 21), "source": "Reported as 7 days from 21 Sep 2026 by third-party pages. NOT checked against Meta's documentation."},
    ])
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT ON whatsapp_entry_windows, whatsapp_entry_window_checks TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_table("whatsapp_entry_window_checks")
    op.drop_table("whatsapp_entry_windows")
    for c in ("entry_point_at", "referral_clid", "referral_url", "referral_headline", "referral_id", "referral_type"):
        op.drop_column("whatsapp_conversations", c)
