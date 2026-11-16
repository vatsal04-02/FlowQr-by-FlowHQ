"""Cashfree recurring billing, plan display names Launch / Growth / Scale.

Revision ID: 0034
Revises: 0032

There is deliberately NO revision 0033. A "card on file for the trial" migration with that number was written but was never applied to production (production went 0032 to this
revision), and the feature was withdrawn. The number is skipped on purpose so that a development database stamped with the withdrawn 0033 cannot silently treat this migration as
already applied: it fails loudly ("Can't locate revision 0033") and is repaired by hand. For the same reason this migration also drops `subscriptions.card_status` if it exists, so a
database that did run the withdrawn migration ends in the same shape as one that did not.

Plan display names: the internal codes (starter, growth, pro) and the prices do not change. `billing_plans.name` becomes Launch / Growth / Scale. A row is renamed only if it
still carries the name migration 0029 gave it, so a name an administrator has edited is never overwritten.
"""
from alembic import op

revision = "0034"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE subscriptions DROP COLUMN IF EXISTS card_status")
    op.execute("UPDATE billing_plans SET name = 'Launch' WHERE code = 'starter' AND name = 'Starter'")
    op.execute("UPDATE billing_plans SET name = 'Scale' WHERE code = 'pro' AND name = 'Pro'")


def downgrade() -> None:
    op.execute("UPDATE billing_plans SET name = 'Starter' WHERE code = 'starter' AND name = 'Launch'")
    op.execute("UPDATE billing_plans SET name = 'Pro' WHERE code = 'pro' AND name = 'Scale'")
