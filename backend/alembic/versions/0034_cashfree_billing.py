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
import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE subscriptions DROP COLUMN IF EXISTS card_status")
    op.execute("UPDATE billing_plans SET name = 'Launch' WHERE code = 'starter' AND name = 'Starter'")
    op.execute("UPDATE billing_plans SET name = 'Scale' WHERE code = 'pro' AND name = 'Pro'")

    # ---- Cashfree columns. All nullable or defaulted: nothing existing changes, no row is rewritten.
    op.add_column("billing_plans", sa.Column("cashfree_plan_id", sa.String(40)))
    op.create_unique_constraint("uq_billing_plans_cashfree_plan_id", "billing_plans", ["cashfree_plan_id"])

    for name, col in (
        ("provider", sa.String(12)), ("cashfree_subscription_id", sa.String(250)), ("cashfree_cf_subscription_id", sa.String(32)),
        ("authorization_status", sa.String(24)), ("trial_entitlement", sa.String(32)), ("trial_started_at", sa.DateTime(timezone=True)), ("first_charge_at", sa.DateTime(timezone=True)), ("next_charge_at", sa.DateTime(timezone=True)),
        ("last_provider_sync_at", sa.DateTime(timezone=True)),
    ):
        op.add_column("subscriptions", sa.Column(name, col))
    op.create_unique_constraint("uq_subscriptions_cashfree_subscription_id", "subscriptions", ["cashfree_subscription_id"])

    for name, col in (
        ("provider", sa.String(12)), ("cashfree_payment_id", sa.String(64)), ("cashfree_cf_payment_id", sa.String(32)), ("payment_type", sa.String(8)),
        ("period_start", sa.DateTime(timezone=True)), ("period_end", sa.DateTime(timezone=True)), ("failure_reason", sa.Text()),
    ):
        op.add_column("payments", sa.Column(name, col))
    op.create_unique_constraint("uq_payments_cashfree_payment_id", "payments", ["cashfree_payment_id"])

    for name, col in (
        ("subscription_ref", sa.String(250)), ("payment_ref", sa.String(64)), ("payload_hash", sa.String(64)),
        ("last_error", sa.String(300)), ("provider_event_time", sa.DateTime(timezone=True)),
    ):
        op.add_column("webhook_events", sa.Column(name, col))
    op.add_column("webhook_events", sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("ix_webhook_events_subscription_ref", "webhook_events", ["subscription_ref"])


def downgrade() -> None:
    # ---- Cashfree columns (Cashfree data is lost on downgrade; Razorpay data is untouched)
    op.drop_index("ix_webhook_events_subscription_ref", table_name="webhook_events")
    for name in ("attempts", "provider_event_time", "last_error", "payload_hash", "payment_ref", "subscription_ref"):
        op.drop_column("webhook_events", name)
    op.drop_constraint("uq_payments_cashfree_payment_id", "payments", type_="unique")
    for name in ("failure_reason", "period_end", "period_start", "payment_type", "cashfree_cf_payment_id", "cashfree_payment_id", "provider"):
        op.drop_column("payments", name)
    op.drop_constraint("uq_subscriptions_cashfree_subscription_id", "subscriptions", type_="unique")
    for name in ("last_provider_sync_at", "next_charge_at", "first_charge_at", "trial_started_at", "trial_entitlement", "authorization_status", "cashfree_cf_subscription_id", "cashfree_subscription_id", "provider"):
        op.drop_column("subscriptions", name)
    op.drop_constraint("uq_billing_plans_cashfree_plan_id", "billing_plans", type_="unique")
    op.drop_column("billing_plans", "cashfree_plan_id")
    op.execute("UPDATE billing_plans SET name = 'Starter' WHERE code = 'starter' AND name = 'Launch'")
    op.execute("UPDATE billing_plans SET name = 'Pro' WHERE code = 'pro' AND name = 'Scale'")
