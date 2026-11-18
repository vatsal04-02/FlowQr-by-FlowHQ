"""WhatsApp automation, Phase 1 foundation: connections, contacts, consent, suppressions, templates, message records, webhook events, add-ons.

Revision ID: 0048
Revises: 0047

Additive only: eight new tables, nothing existing is read, changed or rewritten. Production must be at 0047 first. Numbering: 0048 was verified free across every local and remote branch on 2026-11-19
(highest anywhere is 0047; `feature/cardless-trial` still carries a conflicting 0039 on top of 0037 and must be renumbered when it ships).

* whatsapp_connections   one business's connection to ONE WhatsApp number (access token stored encrypted, never exported). One live connection per business; a phone_number_id belongs to one business at a time.
* whatsapp_contacts      people a business may message (number, optional name, tags). Not consent.
* whatsapp_consents      one consent per purpose, as worded. The application role can INSERT and can UPDATE only the revocation columns: wording, source and time are immutable.
* whatsapp_suppressions  keyed hashes of numbers that opted out of a business's marketing.
* whatsapp_templates     Meta template records (only approved ones can ever be sent).
* whatsapp_messages      message and delivery records (empty until Phase 2 sends; Phase 1 only receives status updates for them).
* whatsapp_webhook_events  sanitised, de-duplicated, signature-verified Meta deliveries.
* tenant_addons          add-ons recorded by hand by an administrator (no billing).
All tables get forced row-level security with the usual tenant policy. No user, membership, subscription or card row is created or altered.
"""
import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0048"
down_revision = "0047"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
TS = lambda: [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),  # noqa: E731
              sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]
TENANTS = ("whatsapp_connections", "whatsapp_contacts", "whatsapp_consents", "whatsapp_suppressions", "whatsapp_templates", "whatsapp_messages", "whatsapp_webhook_events", "tenant_addons")


def _in(col, values):
    return f"{col} in ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "whatsapp_connections",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("waba_id", sa.String(40)), sa.Column("phone_number_id", sa.String(40)), sa.Column("display_phone_number", sa.String(32)),
        sa.Column("verified_name", sa.String(160)), sa.Column("quality_rating", sa.String(16)),
        sa.Column("is_test_number", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("access_token_enc", sa.Text()), sa.Column("token_expires_at", sa.DateTime(timezone=True)), sa.Column("token_checked_at", sa.DateTime(timezone=True)),
        sa.Column("webhook_status", sa.String(12), nullable=False, server_default="unknown"),
        sa.Column("attention_reason", sa.String(200)), sa.Column("state_hash", sa.String(64)), sa.Column("state_expires_at", sa.DateTime(timezone=True)),
        sa.Column("started_by", sa.UUID()), sa.Column("connected_at", sa.DateTime(timezone=True)), sa.Column("disconnected_at", sa.DateTime(timezone=True)),
        *TS(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["started_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(_in("status", ("pending", "connected", "needs_attention", "disconnected")), name="ck_wa_conn_status"),
        sa.CheckConstraint(_in("webhook_status", ("unknown", "subscribed", "failed")), name="ck_wa_conn_webhook"),
    )
    op.create_index("ix_whatsapp_connections_tenant_id", "whatsapp_connections", ["tenant_id"])
    op.create_index("ix_wa_conn_state", "whatsapp_connections", ["state_hash"])
    op.create_index("uq_wa_conn_tenant_live", "whatsapp_connections", ["tenant_id"], unique=True, postgresql_where=sa.text("status <> 'disconnected'"))
    op.create_index("uq_wa_conn_phone_live", "whatsapp_connections", ["phone_number_id"], unique=True, postgresql_where=sa.text("status <> 'disconnected' AND phone_number_id IS NOT NULL"))

    op.create_table(
        "whatsapp_contacts",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False), sa.Column("customer_name", sa.String(120)),
        sa.Column("tags", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("source", sa.String(18), nullable=False), sa.Column("created_by", sa.UUID()), sa.Column("marketing_opted_out_at", sa.DateTime(timezone=True)),
        *TS(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", "phone", name="uq_wa_contact_phone"),
    )
    op.create_index("ix_wa_contact_tenant_created", "whatsapp_contacts", ["tenant_id", "created_at"])

    op.create_table(
        "whatsapp_consents",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("contact_id", sa.UUID(), nullable=False),
        sa.Column("purpose", sa.String(10), nullable=False), sa.Column("source", sa.String(18), nullable=False),
        sa.Column("wording_version", sa.String(24), nullable=False), sa.Column("wording_text", sa.String(600), nullable=False), sa.Column("evidence", sa.String(400)),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False), sa.Column("granted_by", sa.UUID()),
        sa.Column("revoked_at", sa.DateTime(timezone=True)), sa.Column("revoked_source", sa.String(24)), sa.Column("revoked_by", sa.UUID()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["whatsapp_contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(_in("purpose", ("marketing", "utility")), name="ck_wa_consent_purpose"),
        sa.CheckConstraint(_in("source", ("qr_page", "website_form", "customer_message", "owner_entry", "csv_import", "admin_entry")), name="ck_wa_consent_source"),
    )
    op.create_index("uq_wa_consent_active", "whatsapp_consents", ["contact_id", "purpose"], unique=True, postgresql_where=sa.text("revoked_at IS NULL"))
    op.create_index("ix_wa_consent_tenant", "whatsapp_consents", ["tenant_id", "granted_at"])

    op.create_table(
        "whatsapp_suppressions",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("phone_hash", sa.String(64), nullable=False),
        sa.Column("reason", sa.String(24), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "phone_hash", name="uq_wa_suppression"),
    )

    op.create_table(
        "whatsapp_templates",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("meta_template_id", sa.String(40)), sa.Column("template_name", sa.String(80), nullable=False), sa.Column("language", sa.String(12), nullable=False),
        sa.Column("category", sa.String(16), nullable=False), sa.Column("approval_status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("body_text", sa.String(1100)), sa.Column("variable_schema", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("rejection_reason", sa.String(300)), sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        *TS(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["whatsapp_connections.id"], ondelete="CASCADE"),
        sa.CheckConstraint(_in("category", ("marketing", "utility", "authentication")), name="ck_wa_template_category"),
        sa.CheckConstraint(_in("approval_status", ("pending", "approved", "rejected", "paused", "disabled")), name="ck_wa_template_status"),
        sa.UniqueConstraint("connection_id", "template_name", "language", name="uq_wa_template_name"),
    )
    op.create_index("ix_whatsapp_templates_tenant_id", "whatsapp_templates", ["tenant_id"])

    op.create_table(
        "whatsapp_messages",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("connection_id", sa.UUID()), sa.Column("contact_id", sa.UUID()),
        sa.Column("phone_number_id", sa.String(40), nullable=False), sa.Column("meta_message_id", sa.String(120)),
        sa.Column("direction", sa.String(8), nullable=False, server_default="outbound"), sa.Column("category", sa.String(16)), sa.Column("template_id", sa.UUID()),
        sa.Column("delivery_status", sa.String(10), nullable=False, server_default="queued"), sa.Column("error_code", sa.String(20)),
        sa.Column("sent_at", sa.DateTime(timezone=True)), sa.Column("delivered_at", sa.DateTime(timezone=True)), sa.Column("read_at", sa.DateTime(timezone=True)),
        sa.Column("status_updated_at", sa.DateTime(timezone=True)),
        *TS(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["connection_id"], ["whatsapp_connections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["contact_id"], ["whatsapp_contacts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["template_id"], ["whatsapp_templates.id"], ondelete="SET NULL"),
        sa.CheckConstraint(_in("direction", ("outbound", "inbound")), name="ck_wa_msg_direction"),
        sa.CheckConstraint(_in("delivery_status", ("queued", "sent", "delivered", "read", "failed")), name="ck_wa_msg_status"),
    )
    op.create_index("uq_wa_msg_meta", "whatsapp_messages", ["phone_number_id", "meta_message_id"], unique=True, postgresql_where=sa.text("meta_message_id IS NOT NULL"))
    op.create_index("ix_wa_msg_tenant_created", "whatsapp_messages", ["tenant_id", "created_at"])

    op.create_table(
        "whatsapp_webhook_events",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID()), sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("phone_number_id", sa.String(40)), sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(10), nullable=False, server_default="received"), sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.String(300)), sa.Column("received_at", sa.DateTime(timezone=True), nullable=False), sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.CheckConstraint(_in("status", ("received", "processed", "ignored", "failed")), name="ck_wa_event_status"),
        sa.UniqueConstraint("payload_sha256", name="uq_wa_event_payload"),
    )
    op.create_index("ix_whatsapp_webhook_events_tenant_id", "whatsapp_webhook_events", ["tenant_id"])
    op.create_index("ix_wa_event_status_received", "whatsapp_webhook_events", ["status", "received_at"])

    op.create_table(
        "tenant_addons",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("addon_key", sa.String(24), nullable=False),
        sa.Column("status", sa.String(8), nullable=False, server_default="active"), sa.Column("reason", sa.String(300), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False), sa.Column("ended_at", sa.DateTime(timezone=True)), sa.Column("granted_by", sa.UUID()),
        *TS(),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(_in("addon_key", ("whatsapp_starter", "whatsapp_growth", "whatsapp_pro")), name="ck_tenant_addon_key"),
        sa.CheckConstraint(_in("status", ("active", "ended")), name="ck_tenant_addon_status"),
    )
    op.create_index("ix_tenant_addons_tenant_id", "tenant_addons", ["tenant_id"])
    op.create_index("uq_tenant_addon_active_family", "tenant_addons", ["tenant_id"], unique=True, postgresql_where=sa.text("status = 'active' AND addon_key LIKE 'whatsapp_%'"))

    for t in TENANTS:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({COND}) WITH CHECK ({COND})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON whatsapp_connections, whatsapp_contacts, whatsapp_templates, whatsapp_messages, whatsapp_webhook_events TO {APP_ROLE}';
            EXECUTE 'GRANT SELECT, INSERT, DELETE ON whatsapp_consents, whatsapp_suppressions TO {APP_ROLE}';
            EXECUTE 'GRANT UPDATE (revoked_at, revoked_source, revoked_by) ON whatsapp_consents TO {APP_ROLE}';
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON tenant_addons TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    for t in ("tenant_addons", "whatsapp_webhook_events", "whatsapp_messages", "whatsapp_templates", "whatsapp_suppressions", "whatsapp_consents", "whatsapp_contacts", "whatsapp_connections"):
        op.drop_table(t)
