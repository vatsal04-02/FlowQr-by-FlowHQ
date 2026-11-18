"""WhatsApp automation, Phases 2 and 3: dated Meta rates, automations and their runs, campaigns and their recipients, and the send ledger columns on whatsapp_messages.

Revision ID: 0049
Revises: 0048

Additive only: five new tables, four nullable columns on whatsapp_messages. Production must be at 0048 first.

* whatsapp_rates                 dated Meta per-message rates (country, category, effective date, source, verified flag). Global data, readable by every business, never hardcoded in code.
                                 The seed rows are an UNVERIFIED estimate from third-party summaries of Meta's India rate card; an administrator replaces them with Meta's own numbers.
* whatsapp_automations           a business's switched-on helper (review follow-up, enquiry follow-up) with its settings.
* whatsapp_automation_runs       one scheduled send per trigger, with an idempotency key (a trigger can never run twice).
* whatsapp_campaigns             an offer a business approved to send, with the recipient count and estimate it approved.
* whatsapp_campaign_recipients   who a campaign is sending to (one row per customer; a customer is never in a campaign twice).
* whatsapp_messages (+columns)   campaign_id, run_id, idempotency_key (unique), est_rate: the ledger entry for a send and its estimated Meta charge.
Tenant tables get forced row-level security with the usual tenant policy.
"""
import os
from datetime import date
from decimal import Decimal

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
TS = lambda: [sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),  # noqa: E731
              sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]
TENANTS = ("whatsapp_automations", "whatsapp_automation_runs", "whatsapp_campaigns", "whatsapp_campaign_recipients")
SOURCE = "Third-party summaries of Meta's India rate card (not Meta's own page). UNVERIFIED: replace with Meta's current rate card."


def _in(col, values):
    return f"{col} in ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "whatsapp_rates",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("country", sa.String(2), nullable=False), sa.Column("category", sa.String(16), nullable=False),
        sa.Column("rate", sa.Numeric(10, 4), nullable=False), sa.Column("currency", sa.String(3), nullable=False, server_default="INR"), sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("source", sa.String(300), nullable=False), sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", sa.UUID()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(_in("category", ("marketing", "utility", "authentication", "service")), name="ck_wa_rate_category"),
        sa.CheckConstraint("rate >= 0", name="ck_wa_rate_nonneg"),
        sa.UniqueConstraint("country", "category", "effective_from", name="uq_wa_rate"),
    )
    rates = sa.table("whatsapp_rates", sa.column("id", sa.UUID()), sa.column("country", sa.String), sa.column("category", sa.String), sa.column("rate", sa.Numeric), sa.column("currency", sa.String),
                     sa.column("effective_from", sa.Date), sa.column("source", sa.String), sa.column("verified", sa.Boolean))
    import uuid
    op.bulk_insert(rates, [{"id": uuid.uuid4(), "country": "IN", "category": c, "rate": Decimal(r), "currency": "INR", "effective_from": date(2026, 1, 1), "source": SOURCE, "verified": False}
                           for c, r in (("marketing", "0.8631"), ("utility", "0.1150"), ("authentication", "0.1150"), ("service", "0.0000"))])

    op.create_table(
        "whatsapp_automations",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("automation_key", sa.String(24), nullable=False),
        sa.Column("status", sa.String(8), nullable=False, server_default="off"), sa.Column("config", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("activated_at", sa.DateTime(timezone=True)), sa.Column("last_run_at", sa.DateTime(timezone=True)), sa.Column("created_by", sa.UUID()),
        *TS(),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(_in("automation_key", ("review_followup", "enquiry_followup")), name="ck_wa_auto_key"),
        sa.CheckConstraint(_in("status", ("off", "on", "paused")), name="ck_wa_auto_status"),
        sa.UniqueConstraint("tenant_id", "automation_key", name="uq_wa_auto"),
    )
    op.create_index("ix_whatsapp_automations_tenant_id", "whatsapp_automations", ["tenant_id"])

    op.create_table(
        "whatsapp_automation_runs",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("automation_id", sa.UUID(), nullable=False), sa.Column("contact_id", sa.UUID()),
        sa.Column("step", sa.String(16), nullable=False), sa.Column("trigger_ref", sa.String(120), nullable=False), sa.Column("idempotency_key", sa.String(200), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="scheduled"), sa.Column("reason", sa.String(60)), sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False), sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.Column("context", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        *TS(),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["automation_id"], ["whatsapp_automations.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["contact_id"], ["whatsapp_contacts.id"], ondelete="SET NULL"),
        sa.CheckConstraint(_in("status", ("scheduled", "sending", "sent", "skipped", "failed", "cancelled")), name="ck_wa_run_status"),
        sa.UniqueConstraint("idempotency_key", name="uq_wa_run_idem"),
    )
    op.create_index("ix_wa_run_due", "whatsapp_automation_runs", ["status", "scheduled_at"])
    op.create_index("ix_whatsapp_automation_runs_tenant_id", "whatsapp_automation_runs", ["tenant_id"])

    op.create_table(
        "whatsapp_campaigns",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("name", sa.String(120), nullable=False), sa.Column("template_id", sa.UUID()),
        sa.Column("audience", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")), sa.Column("variables", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(10), nullable=False, server_default="draft"), sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("approved_by", sa.UUID()), sa.Column("approved_at", sa.DateTime(timezone=True)), sa.Column("approved_recipients", sa.Integer()), sa.Column("approved_cost", sa.Numeric(12, 4)),
        sa.Column("started_at", sa.DateTime(timezone=True)), sa.Column("finished_at", sa.DateTime(timezone=True)), sa.Column("created_by", sa.UUID()),
        *TS(),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_id"], ["whatsapp_templates.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(_in("status", ("draft", "scheduled", "sending", "paused", "done", "cancelled")), name="ck_wa_campaign_status"),
    )
    op.create_index("ix_whatsapp_campaigns_tenant_id", "whatsapp_campaigns", ["tenant_id"])
    op.create_index("ix_wa_campaign_due", "whatsapp_campaigns", ["status", "scheduled_at"])

    op.create_table(
        "whatsapp_campaign_recipients",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("campaign_id", sa.UUID(), nullable=False), sa.Column("contact_id", sa.UUID(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"), sa.Column("reason", sa.String(60)), sa.Column("message_id", sa.UUID()),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["whatsapp_campaigns.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["contact_id"], ["whatsapp_contacts.id"], ondelete="CASCADE"),
        sa.CheckConstraint(_in("status", ("pending", "sent", "skipped", "failed")), name="ck_wa_recipient_status"),
        sa.UniqueConstraint("campaign_id", "contact_id", name="uq_wa_campaign_recipient"),
    )
    op.create_index("ix_whatsapp_campaign_recipients_tenant_id", "whatsapp_campaign_recipients", ["tenant_id"])
    op.create_index("ix_wa_recipient_pending", "whatsapp_campaign_recipients", ["campaign_id", "status"])

    op.add_column("whatsapp_messages", sa.Column("campaign_id", sa.UUID()))
    op.add_column("whatsapp_messages", sa.Column("run_id", sa.UUID()))
    op.add_column("whatsapp_messages", sa.Column("idempotency_key", sa.String(200)))
    op.add_column("whatsapp_messages", sa.Column("est_rate", sa.Numeric(10, 4)))
    op.create_foreign_key("fk_wa_msg_campaign", "whatsapp_messages", "whatsapp_campaigns", ["campaign_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_wa_msg_run", "whatsapp_messages", "whatsapp_automation_runs", ["run_id"], ["id"], ondelete="SET NULL")
    op.create_index("uq_wa_msg_idem", "whatsapp_messages", ["tenant_id", "idempotency_key"], unique=True, postgresql_where=sa.text("idempotency_key IS NOT NULL"))
    op.create_index("ix_wa_msg_campaign", "whatsapp_messages", ["campaign_id"])
    op.create_foreign_key("fk_wa_recipient_msg", "whatsapp_campaign_recipients", "whatsapp_messages", ["message_id"], ["id"], ondelete="SET NULL")

    for t in TENANTS:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({COND}) WITH CHECK ({COND})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON whatsapp_automations, whatsapp_automation_runs, whatsapp_campaigns, whatsapp_campaign_recipients TO {APP_ROLE}';
            EXECUTE 'GRANT SELECT, INSERT ON whatsapp_rates TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_constraint("fk_wa_recipient_msg", "whatsapp_campaign_recipients", type_="foreignkey")
    op.drop_index("ix_wa_msg_campaign", "whatsapp_messages")
    op.drop_index("uq_wa_msg_idem", "whatsapp_messages")
    op.drop_constraint("fk_wa_msg_run", "whatsapp_messages", type_="foreignkey")
    op.drop_constraint("fk_wa_msg_campaign", "whatsapp_messages", type_="foreignkey")
    for c in ("est_rate", "idempotency_key", "run_id", "campaign_id"):
        op.drop_column("whatsapp_messages", c)
    for t in ("whatsapp_campaign_recipients", "whatsapp_campaigns", "whatsapp_automation_runs", "whatsapp_automations", "whatsapp_rates"):
        op.drop_table(t)
