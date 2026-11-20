"""WhatsApp appointment booking (Phase 9).

Revision ID: 0058
Revises: 0057

Additive, plus one widened check constraint (a new consent source). Production must be at 0057 first. Nothing here sends anything and nothing is on: the platform switch WHATSAPP_BOOKING_ENABLED is off and each
business turns bookings on itself (Growth and Pro tiers).

* whatsapp_booking_settings   one row per business: on/off, how many bookings can overlap (capacity), the slot step, the least notice, how far ahead, reminders on/off and when.
* whatsapp_booking_services   what can be booked: name, minutes, optional price, a buffer after each booking.
* whatsapp_booking_hours      the weekly opening hours (one row per open weekday).
* whatsapp_booking_closed     closed dates (holidays).
* whatsapp_bookings           the bookings. Double-booking is prevented by the server under a lock, never by the AI. A booking is deleted with its customer and with the business.
* whatsapp_consents.source    gains 'whatsapp_booking': the customer said YES in the chat to updates about their visit. It never grants offers or greetings.
* whatsapp_conversations      + booking_consent_ask_id / booking_consent_asked_at: the fixed "would you like reminders? Reply YES" question is waiting for an answer.
Forced row-level security with the usual tenant policy on every new table.
"""
import os

import sqlalchemy as sa
from alembic import op

revision = "0058"
down_revision = "0057"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
OLD_SOURCES = ("qr_page", "website_form", "customer_message", "owner_entry", "csv_import", "admin_entry", "qr_click_to_chat", "keyword_opt_in")
NEW_SOURCES = (*OLD_SOURCES, "whatsapp_booking")
TABLES = ("whatsapp_booking_settings", "whatsapp_booking_services", "whatsapp_booking_hours", "whatsapp_booking_closed", "whatsapp_bookings")


def _in(col, values):
    return f"{col} in ({', '.join(repr(v) for v in values)})"


def _ts():
    return [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def upgrade() -> None:
    op.create_table(
        "whatsapp_booking_settings",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("capacity", sa.Integer(), nullable=False, server_default="1"), sa.Column("slot_step_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("min_notice_minutes", sa.Integer(), nullable=False, server_default="60"), sa.Column("max_days_ahead", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("reminders_enabled", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("reminder_day_hour", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("reminder_soon_hours", sa.Integer(), nullable=False, server_default="2"), *_ts(),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.UniqueConstraint("tenant_id", name="uq_wa_booking_settings_tenant"),
        sa.CheckConstraint("capacity BETWEEN 1 AND 50", name="ck_wa_booking_capacity"), sa.CheckConstraint("slot_step_minutes BETWEEN 5 AND 120", name="ck_wa_booking_step"),
        sa.CheckConstraint("min_notice_minutes BETWEEN 0 AND 10080", name="ck_wa_booking_notice"), sa.CheckConstraint("max_days_ahead BETWEEN 1 AND 180", name="ck_wa_booking_ahead"),
        sa.CheckConstraint("reminder_day_hour BETWEEN 9 AND 20", name="ck_wa_booking_dayhour"), sa.CheckConstraint("reminder_soon_hours BETWEEN 1 AND 6", name="ck_wa_booking_soon"),
    )
    op.create_table(
        "whatsapp_booking_services",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("name", sa.String(120), nullable=False), sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("buffer_minutes", sa.Integer(), nullable=False, server_default="0"), sa.Column("price_inr", sa.Numeric(10, 2)), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()), *_ts(),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.CheckConstraint("duration_minutes BETWEEN 5 AND 480", name="ck_wa_bk_service_duration"), sa.CheckConstraint("buffer_minutes BETWEEN 0 AND 120", name="ck_wa_bk_service_buffer"),
        sa.CheckConstraint("price_inr IS NULL OR price_inr >= 0", name="ck_wa_bk_service_price"),
    )
    op.create_index("ix_whatsapp_booking_services_tenant_id", "whatsapp_booking_services", ["tenant_id"])
    op.create_table(
        "whatsapp_booking_hours",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("weekday", sa.SmallInteger(), nullable=False), sa.Column("opens", sa.Time(), nullable=False),
        sa.Column("closes", sa.Time(), nullable=False), sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "weekday", name="uq_wa_booking_hours_day"), sa.CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_wa_booking_weekday"), sa.CheckConstraint("closes > opens", name="ck_wa_booking_hours_order"),
    )
    op.create_index("ix_whatsapp_booking_hours_tenant_id", "whatsapp_booking_hours", ["tenant_id"])
    op.create_table(
        "whatsapp_booking_closed",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("day", sa.Date(), nullable=False), sa.Column("reason", sa.String(120)),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.UniqueConstraint("tenant_id", "day", name="uq_wa_booking_closed_day"),
    )
    op.create_index("ix_whatsapp_booking_closed_tenant_id", "whatsapp_booking_closed", ["tenant_id"])
    op.create_table(
        "whatsapp_bookings",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("contact_id", sa.UUID(), nullable=False), sa.Column("service_id", sa.UUID()),
        sa.Column("conversation_id", sa.UUID()), sa.Column("code", sa.String(10), nullable=False), sa.Column("service_name", sa.String(120), nullable=False), sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("price_inr", sa.Numeric(10, 2)), sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False), sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("blocks_until", sa.DateTime(timezone=True), nullable=False), sa.Column("status", sa.String(10), nullable=False, server_default="booked"), sa.Column("source", sa.String(10), nullable=False),
        sa.Column("note", sa.String(300)), sa.Column("idem_key", sa.String(120)), sa.Column("created_by", sa.UUID()), sa.Column("done_at", sa.DateTime(timezone=True)), sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column("cancel_reason", sa.String(120)), sa.Column("reminder_day_at", sa.DateTime(timezone=True)), sa.Column("reminder_day_result", sa.String(40)), sa.Column("reminder_soon_at", sa.DateTime(timezone=True)),
        sa.Column("reminder_soon_result", sa.String(40)), *_ts(),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["contact_id"], ["whatsapp_contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["service_id"], ["whatsapp_booking_services.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["conversation_id"], ["whatsapp_conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"), sa.UniqueConstraint("tenant_id", "code", name="uq_wa_booking_code"),
        sa.CheckConstraint(_in("status", ("booked", "done", "no_show", "cancelled")), name="ck_wa_booking_status"), sa.CheckConstraint(_in("source", ("ai", "staff", "api")), name="ck_wa_booking_source"),
        sa.CheckConstraint("ends_at > starts_at AND blocks_until >= ends_at", name="ck_wa_booking_times"),
    )
    op.create_index("ix_whatsapp_bookings_tenant_id", "whatsapp_bookings", ["tenant_id"])
    op.create_index("ix_wa_booking_tenant_start", "whatsapp_bookings", ["tenant_id", "starts_at"])
    op.create_index("ix_wa_booking_contact", "whatsapp_bookings", ["contact_id"])
    op.create_index("uq_wa_booking_idem", "whatsapp_bookings", ["tenant_id", "idem_key"], unique=True, postgresql_where=sa.text("idem_key IS NOT NULL"))

    op.add_column("whatsapp_conversations", sa.Column("booking_consent_ask_id", sa.UUID()))
    op.add_column("whatsapp_conversations", sa.Column("booking_consent_asked_at", sa.DateTime(timezone=True)))
    op.drop_constraint("ck_wa_consent_source", "whatsapp_consents", type_="check")
    op.create_check_constraint("ck_wa_consent_source", "whatsapp_consents", _in("source", NEW_SOURCES))

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
    op.drop_constraint("ck_wa_consent_source", "whatsapp_consents", type_="check")
    op.execute("DELETE FROM whatsapp_consents WHERE source = 'whatsapp_booking'")
    op.create_check_constraint("ck_wa_consent_source", "whatsapp_consents", _in("source", OLD_SOURCES))
    op.drop_column("whatsapp_conversations", "booking_consent_asked_at")
    op.drop_column("whatsapp_conversations", "booking_consent_ask_id")
    for t in ("whatsapp_bookings", "whatsapp_booking_closed", "whatsapp_booking_hours", "whatsapp_booking_services", "whatsapp_booking_settings"):
        op.drop_table(t)
