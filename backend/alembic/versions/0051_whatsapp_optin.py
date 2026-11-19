"""WhatsApp opt-in without collecting a phone number: click-to-chat from the QR review page, and opt-in keywords.

Revision ID: 0051
Revises: 0050

Additive only (plus widening one check constraint). Production must be at 0050 first.

* whatsapp_optin_settings   one row per business: the short per-business code, whether the QR page offers the WhatsApp button, which purpose it asks for (updates | offers | both) and whether to confirm.
* whatsapp_optin_keywords   up to 5 per business: a word a customer can text to the business's number to opt in, the purpose it covers, whether to confirm.
* whatsapp_consents.source  now also allows qr_click_to_chat and keyword_opt_in (both are the customer's own act).
* whatsapp_messages.kind    marks messages that are not offers in the ordinary sense (opt-in confirmations; later, occasion greetings) so the offer-frequency gap ignores them.
Both new tables have forced row-level security with the usual tenant policy.
"""
import os

import sqlalchemy as sa
from alembic import op

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
TS = lambda: [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),  # noqa: E731
              sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]
OLD_SOURCES = ("qr_page", "website_form", "customer_message", "owner_entry", "csv_import", "admin_entry")
NEW_SOURCES = OLD_SOURCES + ("qr_click_to_chat", "keyword_opt_in")


def _in(col, values):
    return f"{col} in ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "whatsapp_optin_settings",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("code", sa.String(10), nullable=False),
        sa.Column("qr_enabled", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("purpose", sa.String(10), nullable=False, server_default="utility"),
        sa.Column("confirm_reply", sa.Boolean(), nullable=False, server_default=sa.true()),
        *TS(),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.CheckConstraint(_in("purpose", ("utility", "marketing", "both")), name="ck_wa_optin_purpose"),
        sa.UniqueConstraint("tenant_id", name="uq_wa_optin_tenant"), sa.UniqueConstraint("code", name="uq_wa_optin_code"),
    )
    op.create_table(
        "whatsapp_optin_keywords",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("keyword", sa.String(20), nullable=False),
        sa.Column("purpose", sa.String(10), nullable=False, server_default="utility"), sa.Column("confirm_reply", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        *TS(),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.CheckConstraint(_in("purpose", ("utility", "marketing", "both")), name="ck_wa_keyword_purpose"),
        sa.CheckConstraint("keyword = lower(keyword)", name="ck_wa_keyword_lower"),
        sa.UniqueConstraint("tenant_id", "keyword", name="uq_wa_keyword"),
    )
    op.create_index("ix_whatsapp_optin_keywords_tenant_id", "whatsapp_optin_keywords", ["tenant_id"])
    for t in ("whatsapp_optin_settings", "whatsapp_optin_keywords"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({COND}) WITH CHECK ({COND})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON whatsapp_optin_settings, whatsapp_optin_keywords TO {APP_ROLE}';
          END IF;
        END $$;
    """)
    op.add_column("whatsapp_messages", sa.Column("kind", sa.String(16)))
    op.drop_constraint("ck_wa_consent_source", "whatsapp_consents", type_="check")
    op.create_check_constraint("ck_wa_consent_source", "whatsapp_consents", _in("source", NEW_SOURCES))


def downgrade() -> None:
    op.drop_constraint("ck_wa_consent_source", "whatsapp_consents", type_="check")
    op.execute("DELETE FROM whatsapp_consents WHERE source IN ('qr_click_to_chat', 'keyword_opt_in')")
    op.create_check_constraint("ck_wa_consent_source", "whatsapp_consents", _in("source", OLD_SOURCES))
    op.drop_column("whatsapp_messages", "kind")
    op.drop_table("whatsapp_optin_keywords")
    op.drop_table("whatsapp_optin_settings")
