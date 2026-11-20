"""WhatsApp AI auto-reply assistant (Phase 8).

Revision ID: 0057
Revises: 0056

Additive only. Production must be at 0056 first. Nothing here sends anything and nothing is on: the platform switches WHATSAPP_AI_ENABLED and WHATSAPP_AI_TERMS_VERIFIED are off,
each business turns its own assistant on, and the assistant stays "unavailable" until an administrator has the AI provider's written data terms.

* whatsapp_ai_quotas              DATED, append-only: how many assistant replies a month each WhatsApp tier includes (a change is a new row with a new date; seeded conservatively, Starter 0).
* whatsapp_ai_settings            one row per business: assistant on/off, the owner's acknowledgement that customer messages go to an AI provider (who and when), the tone.
* whatsapp_knowledge_items        what the owner tells the assistant: about, address, hours, services (with prices), FAQs, policies, booking rules. Offers are NOT a kind here: the assistant never sees offers.
* whatsapp_ai_runs                one row per assistant reply attempt: provider, model version, tokens, latency, outcome, handoff reason, the owner's thumbs up/down. No customer phone number.
* whatsapp_unanswered_questions   what customers asked that the knowledge could not answer, so the owner can add it. One row per conversation and question; it is deleted with the conversation (and so with the customer).
* whatsapp_conversations          + ai_off (per-conversation pause), ai_disclosed_at (the "automated assistant" line was sent), holding_sent_at (the "someone will reply" line was sent), ai_pseudonym.
Forced row-level security with the usual tenant policy on every per-business table.
"""
import os
import uuid
from datetime import date

import sqlalchemy as sa
from alembic import op

revision = "0057"
down_revision = "0056"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
KINDS = ("about", "address", "hours", "service", "faq", "policy", "booking_rule")
OUTCOMES = ("replied", "handoff", "refused", "holding", "blocked", "error")


def _in(col, values):
    return f"{col} in ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "whatsapp_ai_quotas",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("addon_key", sa.String(24), nullable=False), sa.Column("monthly_replies", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False), sa.Column("note", sa.String(300), nullable=False), sa.Column("created_by", sa.UUID()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"), sa.UniqueConstraint("addon_key", "effective_from", name="uq_wa_ai_quota"),
        sa.CheckConstraint("monthly_replies >= 0", name="ck_wa_ai_quota_nonneg"), sa.CheckConstraint(_in("addon_key", ("whatsapp_starter", "whatsapp_growth", "whatsapp_pro")), name="ck_wa_ai_quota_key"),
    )
    quotas = sa.table("whatsapp_ai_quotas", sa.column("id", sa.UUID()), sa.column("addon_key", sa.String()), sa.column("monthly_replies", sa.Integer()), sa.column("effective_from", sa.Date()), sa.column("note", sa.String()))
    note = "Starting value, deliberately low for the limited beta. Adjust from the tokens and latency recorded in whatsapp_ai_runs."
    op.bulk_insert(quotas, [
        {"id": uuid.uuid4(), "addon_key": "whatsapp_starter", "monthly_replies": 0, "effective_from": date(2026, 1, 1), "note": "The assistant is a Growth and Pro feature."},
        {"id": uuid.uuid4(), "addon_key": "whatsapp_growth", "monthly_replies": 150, "effective_from": date(2026, 1, 1), "note": note},
        {"id": uuid.uuid4(), "addon_key": "whatsapp_pro", "monthly_replies": 400, "effective_from": date(2026, 1, 1), "note": note},
    ])

    op.create_table(
        "whatsapp_ai_settings",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("privacy_ack_at", sa.DateTime(timezone=True)), sa.Column("privacy_ack_by", sa.UUID()), sa.Column("tone", sa.String(120)), sa.Column("quota_warned_month", sa.String(7)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["privacy_ack_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tenant_id", name="uq_wa_ai_settings_tenant"),
    )
    op.create_table(
        "whatsapp_knowledge_items",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("kind", sa.String(14), nullable=False), sa.Column("title", sa.String(120)),
        sa.Column("body", sa.String(1200), nullable=False), sa.Column("price_inr", sa.Numeric(10, 2)), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.CheckConstraint(_in("kind", KINDS), name="ck_wa_knowledge_kind"),
        sa.CheckConstraint("price_inr IS NULL OR price_inr >= 0", name="ck_wa_knowledge_price"),
    )
    op.create_index("ix_whatsapp_knowledge_items_tenant_id", "whatsapp_knowledge_items", ["tenant_id"])
    op.create_table(
        "whatsapp_ai_runs",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("conversation_id", sa.UUID()), sa.Column("message_id", sa.UUID()),
        sa.Column("provider", sa.String(40)), sa.Column("model_version", sa.String(80)), sa.Column("prompt_tokens", sa.Integer()), sa.Column("completion_tokens", sa.Integer()),
        sa.Column("calls", sa.Integer(), nullable=False, server_default="0"), sa.Column("latency_ms", sa.Integer()), sa.Column("outcome", sa.String(10), nullable=False), sa.Column("handoff_reason", sa.String(40)),
        sa.Column("counted", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("is_test", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("feedback", sa.String(4)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["conversation_id"], ["whatsapp_conversations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["message_id"], ["whatsapp_conversation_messages.id"], ondelete="SET NULL"),
        sa.CheckConstraint(_in("outcome", OUTCOMES), name="ck_wa_ai_run_outcome"), sa.CheckConstraint("feedback IS NULL OR feedback in ('up', 'down')", name="ck_wa_ai_run_feedback"),
    )
    op.create_index("ix_whatsapp_ai_runs_tenant_id", "whatsapp_ai_runs", ["tenant_id"])
    op.create_index("ix_wa_ai_run_tenant_created", "whatsapp_ai_runs", ["tenant_id", "created_at"])
    op.create_table(
        "whatsapp_unanswered_questions",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("conversation_id", sa.UUID()), sa.Column("question", sa.String(300), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"), sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("last_asked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["conversation_id"], ["whatsapp_conversations.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_whatsapp_unanswered_questions_tenant_id", "whatsapp_unanswered_questions", ["tenant_id"])

    op.add_column("whatsapp_conversations", sa.Column("ai_off", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("whatsapp_conversations", sa.Column("ai_disclosed_at", sa.DateTime(timezone=True)))
    op.add_column("whatsapp_conversations", sa.Column("holding_sent_at", sa.DateTime(timezone=True)))
    op.add_column("whatsapp_conversations", sa.Column("ai_pseudonym", sa.String(16)))

    for t in ("whatsapp_ai_settings", "whatsapp_knowledge_items", "whatsapp_ai_runs", "whatsapp_unanswered_questions"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({COND}) WITH CHECK ({COND})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON whatsapp_ai_settings, whatsapp_knowledge_items, whatsapp_ai_runs, whatsapp_unanswered_questions TO {APP_ROLE}';
            EXECUTE 'GRANT SELECT, INSERT ON whatsapp_ai_quotas TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    for c in ("ai_pseudonym", "holding_sent_at", "ai_disclosed_at", "ai_off"):
        op.drop_column("whatsapp_conversations", c)
    for t in ("whatsapp_unanswered_questions", "whatsapp_ai_runs", "whatsapp_knowledge_items", "whatsapp_ai_settings", "whatsapp_ai_quotas"):
        op.drop_table(t)
