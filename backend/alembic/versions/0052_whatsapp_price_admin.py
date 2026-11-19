"""Meta price admin: a free-allowance column, an append-only record of price checks, and the October 2026 India starting values (all UNVERIFIED).

Revision ID: 0052
Revises: 0051

Additive only. Production must be at 0051 first.

* whatsapp_rates.free_per_number_month   how many messages of that category Meta gives free per number per month (0 = none). Rate rows are still never edited; this is part of a row when it is written.
* whatsapp_rate_verifications            append-only: who checked a rate row against Meta's own rate card, when, what they decided (verified or not) and a note. The rate row itself is never touched.
                                         The price screen shows the LATEST check for each row. The app role can read and add, never change or delete.
* whatsapp_campaigns.approved_price      what the owner was shown when they approved an offer: the rate, the price date it came from and whether it was verified then. Offers keep that estimate;
                                         only new estimates use newer prices.
* four starting rows, effective 2026-10-01, all marked UNVERIFIED: India marketing 1.09, utility 0.145, authentication 0.145, service 0.145 (the first 1,000 service messages per number per month are free).
  They come from AiSensy's pricing page, NOT from Meta, and have NOT been checked against Meta's rate card. Older rows stay as history; nothing is overwritten.
"""
import os
import uuid
from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
SOURCE = "AiSensy pricing page, not Meta, unverified. Starting value for India, effective 1 Oct 2026; not yet checked against Meta's own rate card."
ROWS = (("marketing", "1.0900", 0), ("utility", "0.1450", 0), ("authentication", "0.1450", 0), ("service", "0.1450", 1000))


def upgrade() -> None:
    op.add_column("whatsapp_rates", sa.Column("free_per_number_month", sa.Integer(), nullable=False, server_default="0"))
    op.create_check_constraint("ck_wa_rate_free", "whatsapp_rates", "free_per_number_month >= 0")
    op.add_column("whatsapp_campaigns", sa.Column("approved_price", JSONB(), nullable=True))
    op.create_table(
        "whatsapp_rate_verifications",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("rate_id", sa.UUID(), nullable=False), sa.Column("verified", sa.Boolean(), nullable=False),
        sa.Column("note", sa.String(300), nullable=False), sa.Column("verified_by", sa.UUID()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["rate_id"], ["whatsapp_rates.id"], ondelete="RESTRICT"), sa.ForeignKeyConstraint(["verified_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_wa_rate_verif_rate", "whatsapp_rate_verifications", ["rate_id", "created_at"])
    rates = sa.table("whatsapp_rates", sa.column("id", sa.UUID()), sa.column("country", sa.String), sa.column("category", sa.String), sa.column("rate", sa.Numeric), sa.column("currency", sa.String),
                     sa.column("effective_from", sa.Date), sa.column("source", sa.String), sa.column("verified", sa.Boolean), sa.column("free_per_number_month", sa.Integer))
    op.bulk_insert(rates, [{"id": uuid.uuid4(), "country": "IN", "category": c, "rate": Decimal(r), "currency": "INR", "effective_from": date(2026, 10, 1), "source": SOURCE, "verified": False,
                            "free_per_number_month": free} for c, r, free in ROWS])
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT ON whatsapp_rate_verifications TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_column("whatsapp_campaigns", "approved_price")
    op.drop_table("whatsapp_rate_verifications")
    op.execute(f"DELETE FROM whatsapp_rates WHERE country = 'IN' AND effective_from = DATE '2026-10-01' AND source = '{SOURCE.replace(chr(39), chr(39) * 2)}'")
    op.drop_constraint("ck_wa_rate_free", "whatsapp_rates", type_="check")
    op.drop_column("whatsapp_rates", "free_per_number_month")
