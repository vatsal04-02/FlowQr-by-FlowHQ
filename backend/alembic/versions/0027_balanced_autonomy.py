"""Balanced Autonomy: actions, approvals, tamper-protected intervention history, rank follow-ups, per-tenant autonomy settings, platform emergency stop.

Revision ID: 0027
Revises: 0026

* agent_actions / agent_action_approvals / agent_intervention_events / agent_rank_followups: tenant-scoped, RLS enabled AND forced.
* agent_intervention_events is APPEND-ONLY: the app role gets SELECT and INSERT only, and a trigger rejects UPDATE, DELETE and TRUNCATE for everyone. The one
  exception is deleting a whole business (account deletion sets the transaction-local flag app.history_purge), because its data must be erasable.
* agent_settings: autonomy_enabled (default OFF), per-action-type permissions, a daily execution limit, and the automatic-suspension state.
* platform_controls: runtime platform switches (the autonomy emergency stop).
"""
import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
STATUSES = ("pending_approval", "approved", "executing", "executed", "failed", "rejected", "expired", "invalidated", "blocked", "canceled")
TABLES = ("agent_actions", "agent_action_approvals", "agent_intervention_events", "agent_rank_followups")


def _grant(table: str, privileges: str) -> None:
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT {privileges} ON {table} TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def _rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({COND}) WITH CHECK ({COND})")


def upgrade() -> None:
    op.create_table(
        "agent_actions",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("google_location_id", sa.UUID(), sa.ForeignKey("google_locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.UUID()),
        sa.Column("action_type", sa.String(40), nullable=False),
        sa.Column("field_key", sa.String(40), nullable=False),
        sa.Column("trigger", sa.String(60), nullable=False),
        sa.Column("problem", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("expected_outcome", sa.Text(), nullable=False),
        sa.Column("evidence", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("source", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("current_value", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("proposed_value", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("base_fingerprint", sa.String(64), nullable=False),
        sa.Column("value_hash", sa.String(64), nullable=False),
        sa.Column("facts_fingerprint", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("policy_level", sa.SmallInteger(), nullable=False),
        sa.Column("effective_type", sa.String(40), nullable=False),
        sa.Column("risk_level", sa.String(8), nullable=False),
        sa.Column("policy_reasons", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("authorization", sa.String(16), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending_approval"),
        sa.Column("proposed_by", sa.String(8), nullable=False),
        sa.Column("proposed_by_user", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("executed_at", sa.DateTime(timezone=True)),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("google_result", JSONB()),
        sa.Column("verification", JSONB()),
        sa.Column("baseline", JSONB()),
        sa.Column("outcome", JSONB()),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status in (" + ",".join(f"'{s}'" for s in STATUSES) + ")", name="ck_agent_action_status"),
        sa.CheckConstraint("policy_level between 1 and 3", name="ck_agent_action_level"),
    )
    op.create_index("uq_agent_actions_idempotency", "agent_actions", ["tenant_id", "idempotency_key"], unique=True,
                    postgresql_where=sa.text("status in ('pending_approval','approved','executing','executed')"))
    op.create_index("uq_agent_actions_inflight", "agent_actions", ["google_location_id", "field_key"], unique=True, postgresql_where=sa.text("status = 'executing'"))
    op.create_index("ix_agent_actions_due", "agent_actions", ["status", "next_attempt_at"])
    op.create_index("ix_agent_actions_tenant", "agent_actions", ["tenant_id", "status", "created_at"])

    op.create_table(
        "agent_action_approvals",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_id", sa.UUID(), sa.ForeignKey("agent_actions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("basis", sa.String(24), nullable=False),
        sa.Column("authorized_by", sa.UUID(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("reason", sa.Text()),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("scope", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("scope_hash", sa.String(64), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True)),
        sa.Column("invalidated_reason", sa.Text()),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("decision in ('approved','rejected','auto_authorized')", name="ck_agent_approval_decision"),
    )
    op.create_index("ix_agent_approvals_action", "agent_action_approvals", ["action_id", "decided_at"])

    op.create_table(
        "agent_intervention_events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_id", sa.UUID(), sa.ForeignKey("agent_actions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(8), nullable=False),
        sa.Column("user_id", sa.UUID()),
        sa.Column("data", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("action_id", "seq", name="uq_agent_event_seq"),
    )
    op.create_index("ix_agent_events_tenant", "agent_intervention_events", ["tenant_id", "created_at"])

    op.create_table(
        "agent_rank_followups",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("action_id", sa.UUID(), sa.ForeignKey("agent_actions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("google_location_id", sa.UUID(), sa.ForeignKey("google_locations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("day_offset", sa.SmallInteger(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("measured_at", sa.DateTime(timezone=True)),
        sa.Column("result", JSONB()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("action_id", "day_offset", name="uq_agent_followup"),
        sa.CheckConstraint("status in ('pending','done','deferred','skipped')", name="ck_agent_followup_status"),
    )
    op.create_index("ix_agent_followups_due", "agent_rank_followups", ["status", "due_at"])

    for t in TABLES:
        _rls(t)
    _grant("agent_actions", "SELECT, INSERT, UPDATE")
    _grant("agent_action_approvals", "SELECT, INSERT, UPDATE")
    _grant("agent_intervention_events", "SELECT, INSERT")  # append-only for the app: no UPDATE, no DELETE
    _grant("agent_rank_followups", "SELECT, INSERT, UPDATE")

    op.execute("""
        CREATE OR REPLACE FUNCTION agent_events_append_only() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' AND current_setting('app.history_purge', true) = 'on' THEN
            RETURN OLD;  -- only the deletion of a whole business may erase its history
          END IF;
          RAISE EXCEPTION 'agent_intervention_events is append-only (% refused)', TG_OP USING ERRCODE = '42501';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("CREATE TRIGGER agent_events_no_change BEFORE UPDATE OR DELETE ON agent_intervention_events FOR EACH ROW EXECUTE FUNCTION agent_events_append_only()")
    op.execute("CREATE TRIGGER agent_events_no_truncate BEFORE TRUNCATE ON agent_intervention_events FOR EACH STATEMENT EXECUTE FUNCTION agent_events_append_only()")

    op.add_column("agent_settings", sa.Column("autonomy_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("agent_settings", sa.Column("autonomy_permissions", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("agent_settings", sa.Column("autonomy_permissions_by", sa.UUID()))
    op.add_column("agent_settings", sa.Column("autonomy_permissions_at", sa.DateTime(timezone=True)))
    op.add_column("agent_settings", sa.Column("autonomy_daily_limit", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("agent_settings", sa.Column("autonomy_suspended_at", sa.DateTime(timezone=True)))
    op.add_column("agent_settings", sa.Column("autonomy_suspended_reason", sa.Text()))
    op.add_column("agent_settings", sa.Column("autonomy_failure_streak", sa.Integer(), nullable=False, server_default="0"))

    op.create_table(
        "platform_controls",
        sa.Column("key", sa.String(60), nullable=False),
        sa.Column("value", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_by", sa.UUID()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("key"),
    )
    _grant("platform_controls", "SELECT, INSERT, UPDATE")


def downgrade() -> None:
    op.drop_table("platform_controls")
    for c in ("autonomy_failure_streak", "autonomy_suspended_reason", "autonomy_suspended_at", "autonomy_daily_limit", "autonomy_permissions_at",
              "autonomy_permissions_by", "autonomy_permissions", "autonomy_enabled"):
        op.drop_column("agent_settings", c)
    op.execute("SET LOCAL app.history_purge = 'on'")
    op.execute("DROP TRIGGER IF EXISTS agent_events_no_truncate ON agent_intervention_events")
    op.execute("DROP TRIGGER IF EXISTS agent_events_no_change ON agent_intervention_events")
    for t in ("agent_rank_followups", "agent_intervention_events", "agent_action_approvals", "agent_actions"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {t}")
        op.drop_table(t)
    op.execute("DROP FUNCTION IF EXISTS agent_events_append_only()")
