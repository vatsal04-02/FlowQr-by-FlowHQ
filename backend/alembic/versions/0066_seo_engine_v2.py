"""Local SEO engine V2: two more action statuses and a recorded validation step (docs/LOCAL_SEO_ENGINE_V2_IMPLEMENTATION.md).

Revision ID: 0066
Revises: 0065

Additive and reversible.
  * `recommended`  the engine found an improvement and drafted the exact change, but it cannot be executed (the customer-write policy gate is closed for this
                   profile). The owner sees the before/after and can apply it in Google themselves. It owns the idempotency key, so it is never proposed twice.
  * `superseded`   a recommendation or proposal that stopped being the right change because the profile changed (the owner edited it elsewhere, or Google did).
  * `validation_status` / `validation`  the result of the dry-run (Google's `validateOnly`, or the metadata check for attributes) made before any write.
No new table: nothing here needs a new row-level-security policy, export entry or deletion entry.
"""
import sqlalchemy as sa
from alembic import op

revision = "0066"
down_revision = "0065"
branch_labels = None
depends_on = None

OLD = ("pending_approval", "approved", "executing", "executed", "failed", "rejected", "expired", "invalidated", "blocked", "canceled")
NEW = OLD + ("recommended", "superseded")
OLD_LIVE = "status in ('pending_approval','approved','executing','executed')"
NEW_LIVE = "status in ('recommended','pending_approval','approved','executing','executed')"


def _check(statuses) -> str:
    return "status in (" + ",".join(f"'{s}'" for s in statuses) + ")"


def upgrade() -> None:
    op.add_column("agent_actions", sa.Column("validation_status", sa.String(12)))
    op.add_column("agent_actions", sa.Column("validation", sa.dialects.postgresql.JSONB()))
    op.drop_constraint("ck_agent_action_status", "agent_actions", type_="check")
    op.create_check_constraint("ck_agent_action_status", "agent_actions", _check(NEW))
    op.drop_index("uq_agent_actions_idempotency", table_name="agent_actions")
    op.create_index("uq_agent_actions_idempotency", "agent_actions", ["tenant_id", "idempotency_key"], unique=True, postgresql_where=sa.text(NEW_LIVE))


def downgrade() -> None:
    op.execute("UPDATE agent_actions SET status = 'canceled' WHERE status IN ('recommended','superseded')")
    op.drop_index("uq_agent_actions_idempotency", table_name="agent_actions")
    op.create_index("uq_agent_actions_idempotency", "agent_actions", ["tenant_id", "idempotency_key"], unique=True, postgresql_where=sa.text(OLD_LIVE))
    op.drop_constraint("ck_agent_action_status", "agent_actions", type_="check")
    op.create_check_constraint("ck_agent_action_status", "agent_actions", _check(OLD))
    op.drop_column("agent_actions", "validation")
    op.drop_column("agent_actions", "validation_status")
