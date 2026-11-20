"""WhatsApp two-way conversations and the inbox (Phase 7).

Revision ID: 0056
Revises: 0055

Additive only. Production must be at 0055 first. Nothing here sends anything and nothing is on: the platform switch WHATSAPP_CONVERSATIONS_ENABLED is off and each business turns its own inbox on.

* whatsapp_conversation_settings   one row per business: inbox on/off, how long message text is kept (30 to 365 days, default 90), how long the assistant stays quiet after a person takes over,
                                   how long to wait for more messages before anyone answers, whether to email the owner when a conversation needs a person.
* whatsapp_conversations           one per customer; the 24-hour customer-service window is measured from the customer's last message; status open | needs_human | closed; the reason for a handoff.
* whatsapp_conversation_messages   the messages, with who sent each (customer, assistant, a named staff member, or an automatic message).
All three have forced row-level security with the usual tenant policy. A conversation is deleted with its customer (foreign key) and with the business.
"""
import os

import sqlalchemy as sa
from alembic import op

revision = "0056"
down_revision = "0055"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
TS = lambda: [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),  # noqa: E731
              sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def _in(col, values):
    return f"{col} in ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "whatsapp_conversation_settings",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="90"), sa.Column("takeover_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("debounce_seconds", sa.Integer(), nullable=False, server_default="4"), sa.Column("notify_email", sa.Boolean(), nullable=False, server_default=sa.true()), *TS(),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.UniqueConstraint("tenant_id", name="uq_wa_conv_settings_tenant"),
        sa.CheckConstraint("retention_days BETWEEN 30 AND 365", name="ck_wa_conv_retention"), sa.CheckConstraint("takeover_minutes BETWEEN 5 AND 1440", name="ck_wa_conv_takeover"),
        sa.CheckConstraint("debounce_seconds BETWEEN 2 AND 10", name="ck_wa_conv_debounce"),
    )
    op.create_table(
        "whatsapp_conversations",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("contact_id", sa.UUID(), nullable=False), sa.Column("code", sa.String(12), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="open"), sa.Column("last_customer_message_at", sa.DateTime(timezone=True)), sa.Column("last_outbound_at", sa.DateTime(timezone=True)),
        sa.Column("last_message_at", sa.DateTime(timezone=True)), sa.Column("unread_count", sa.Integer(), nullable=False, server_default="0"), sa.Column("awaiting_reply", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("assigned_to", sa.UUID()),
        sa.Column("handoff_reason", sa.String(40)), sa.Column("handoff_at", sa.DateTime(timezone=True)), sa.Column("ai_paused_until", sa.DateTime(timezone=True)), sa.Column("reply_due_at", sa.DateTime(timezone=True)),
        sa.Column("last_notified_at", sa.DateTime(timezone=True)), sa.Column("source", sa.String(16), nullable=False, server_default="organic"), *TS(),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["contact_id"], ["whatsapp_contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_to"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "contact_id", name="uq_wa_conv_contact"), sa.UniqueConstraint("tenant_id", "code", name="uq_wa_conv_code"),
        sa.CheckConstraint(_in("status", ("open", "needs_human", "closed")), name="ck_wa_conv_status"),
    )
    op.create_index("ix_whatsapp_conversations_tenant_id", "whatsapp_conversations", ["tenant_id"])
    op.create_index("ix_wa_conv_tenant_last", "whatsapp_conversations", ["tenant_id", "last_message_at"])
    op.create_index("ix_wa_conv_due", "whatsapp_conversations", ["reply_due_at"], postgresql_where=sa.text("reply_due_at IS NOT NULL"))
    op.create_table(
        "whatsapp_conversation_messages",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("conversation_id", sa.UUID(), nullable=False), sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("sender_type", sa.String(10), nullable=False), sa.Column("staff_user_id", sa.UUID()), sa.Column("text", sa.String(4096)), sa.Column("msg_type", sa.String(16), nullable=False, server_default="text"),
        sa.Column("meta_message_id", sa.String(120)), sa.Column("ledger_id", sa.UUID()), sa.Column("delivery_status", sa.String(10), nullable=False, server_default="received"), sa.Column("error_code", sa.String(20)),
        sa.Column("template_key", sa.String(40)), sa.Column("marketing_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("via_app", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["conversation_id"], ["whatsapp_conversations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["staff_user_id"], ["users.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["ledger_id"], ["whatsapp_messages.id"], ondelete="SET NULL"),
        sa.CheckConstraint(_in("direction", ("outbound", "inbound")), name="ck_wa_convmsg_direction"), sa.CheckConstraint(_in("sender_type", ("customer", "ai", "staff", "system")), name="ck_wa_convmsg_sender"),
        sa.CheckConstraint(_in("delivery_status", ("received", "queued", "sent", "delivered", "read", "failed")), name="ck_wa_convmsg_status"),
    )
    op.create_index("ix_whatsapp_conversation_messages_tenant_id", "whatsapp_conversation_messages", ["tenant_id"])
    op.create_index("ix_wa_convmsg_conv_created", "whatsapp_conversation_messages", ["conversation_id", "created_at"])
    op.create_index("uq_wa_convmsg_meta", "whatsapp_conversation_messages", ["tenant_id", "meta_message_id"], unique=True, postgresql_where=sa.text("meta_message_id IS NOT NULL"))
    for t in ("whatsapp_conversation_settings", "whatsapp_conversations", "whatsapp_conversation_messages"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({COND}) WITH CHECK ({COND})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON whatsapp_conversation_settings, whatsapp_conversations, whatsapp_conversation_messages TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_table("whatsapp_conversation_messages")
    op.drop_table("whatsapp_conversations")
    op.drop_table("whatsapp_conversation_settings")
