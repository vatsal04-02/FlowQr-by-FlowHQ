"""WhatsApp integrations: API keys, idempotent inbound API, signed outbound webhooks (Phase 10).

Revision ID: 0059
Revises: 0058

Additive, plus one widened check constraint (a new consent source). Production must be at 0058 first. Nothing here is on: the platform switch WHATSAPP_INTEGRATIONS_ENABLED is off, and the feature is part of the Pro tier only.

* whatsapp_api_keys           a business's keys. Only a SHA-256 hash of a key is stored (the key itself is shown once, at creation). Scoped, revocable, expiring, rate-limited.
* whatsapp_api_requests       the answer to every idempotent POST, so a retried request returns the first answer and never does the work twice (kept 48 hours).
* whatsapp_webhook_endpoints  where a business wants events sent. The signing secret is stored encrypted and shown once.
* whatsapp_webhook_deliveries one row per event per endpoint: attempts, next attempt, last status. Retried with backoff, then marked dead (kept 14 days). Never holds message text.
* whatsapp_consents.source    gains 'api_integration': a consent recorded through the API needs the same attested evidence as one typed in by the owner.
Forced row-level security with the usual tenant policy on every new table.
"""
import os

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision = "0059"
down_revision = "0058"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
OLD_SOURCES = ("qr_page", "website_form", "customer_message", "owner_entry", "csv_import", "admin_entry", "qr_click_to_chat", "keyword_opt_in", "whatsapp_booking")
NEW_SOURCES = (*OLD_SOURCES, "api_integration")
TABLES = ("whatsapp_api_keys", "whatsapp_api_requests", "whatsapp_webhook_endpoints", "whatsapp_webhook_deliveries")


def _in(col, values):
    return f"{col} in ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "whatsapp_api_keys",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("name", sa.String(80), nullable=False), sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(64), nullable=False), sa.Column("scopes", pg.JSONB(), nullable=False, server_default="[]"), sa.Column("rate_limit_per_min", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("created_by", sa.UUID()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("last_used_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)), sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("key_hash", name="uq_wa_api_key_hash"), sa.CheckConstraint("rate_limit_per_min BETWEEN 10 AND 600", name="ck_wa_api_key_rate"),
    )
    op.create_index("ix_whatsapp_api_keys_tenant_id", "whatsapp_api_keys", ["tenant_id"])
    op.create_table(
        "whatsapp_api_requests",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("key_id", sa.UUID(), nullable=False), sa.Column("idem_key", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False), sa.Column("status_code", sa.Integer(), nullable=False), sa.Column("response", pg.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["key_id"], ["whatsapp_api_keys.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "key_id", "idem_key", name="uq_wa_api_request"),
    )
    op.create_index("ix_whatsapp_api_requests_tenant_id", "whatsapp_api_requests", ["tenant_id"])
    op.create_table(
        "whatsapp_webhook_endpoints",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("url", sa.String(500), nullable=False), sa.Column("secret_enc", sa.Text(), nullable=False),
        sa.Column("secret_hint", sa.String(8), nullable=False), sa.Column("events", pg.JSONB(), nullable=False, server_default="[]"), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("disabled_reason", sa.String(120)), sa.Column("failure_streak", sa.Integer(), nullable=False, server_default="0"), sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_failure_at", sa.DateTime(timezone=True)), sa.Column("created_by", sa.UUID()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_whatsapp_webhook_endpoints_tenant_id", "whatsapp_webhook_endpoints", ["tenant_id"])
    op.create_table(
        "whatsapp_webhook_deliveries",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("endpoint_id", sa.UUID(), nullable=False), sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False), sa.Column("payload", pg.JSONB(), nullable=False), sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"), sa.Column("next_attempt_at", sa.DateTime(timezone=True)), sa.Column("last_status_code", sa.Integer()), sa.Column("last_error", sa.String(120)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["endpoint_id"], ["whatsapp_webhook_endpoints.id"], ondelete="CASCADE"),
        sa.CheckConstraint(_in("status", ("pending", "delivered", "dead")), name="ck_wa_delivery_status"),
    )
    op.create_index("ix_whatsapp_webhook_deliveries_tenant_id", "whatsapp_webhook_deliveries", ["tenant_id"])
    op.create_index("ix_wa_delivery_due", "whatsapp_webhook_deliveries", ["next_attempt_at"], postgresql_where=sa.text("status = 'pending'"))
    op.create_index("ix_wa_delivery_endpoint", "whatsapp_webhook_deliveries", ["endpoint_id", "created_at"])
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
    op.execute("DELETE FROM whatsapp_consents WHERE source = 'api_integration'")
    op.create_check_constraint("ck_wa_consent_source", "whatsapp_consents", _in("source", OLD_SOURCES))
    for t in ("whatsapp_webhook_deliveries", "whatsapp_webhook_endpoints", "whatsapp_api_requests", "whatsapp_api_keys"):
        op.drop_table(t)
