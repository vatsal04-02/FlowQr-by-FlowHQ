"""AI allowances per plan: Launch 150/150, Growth 300/300, Scale 500/500 (owner decision 2026-11-25).

Revision ID: 0071
Revises: 0070

Data only: updates the three sold plan rows in billing_plans. Existing subscriptions keep the allowance they were sold with (it is a snapshot on the subscription row), so nobody who
has already paid loses anything; new purchases, renewals and plan changes pick up the new numbers. Downgrade restores 200/400/800.
"""
from alembic import op

revision = "0071"
down_revision = "0070"
branch_labels = None
depends_on = None


def _set(rows) -> None:
    for code, n in rows:
        op.execute(f"UPDATE billing_plans SET review_generations = {n}, review_replies = {n}, monthly_ai_generations = {2 * n} WHERE code = '{code}'")


def upgrade() -> None:
    _set((("starter", 150), ("growth", 300), ("pro", 500)))


def downgrade() -> None:
    _set((("starter", 200), ("growth", 400), ("pro", 800)))
