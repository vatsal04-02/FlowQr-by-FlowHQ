"""Template-based automatic review replies, and autonomy switched on by default.

Revision ID: 0031
Revises: 0030

Owner decision, 2026-11-15: (1) autonomy is ON for every business, with an off switch; (2) positive reviews (4 and 5 stars) are answered automatically from a template, with an off switch and a
cap that follows the plan. This REPLACES the earlier rule that every reply needed a person. Sensitive and low-rating reviews still always go to a person.

* agent_settings.autonomy_enabled: default ON for new rows, and every existing business is switched ON. (Each action type is still governed by its own permission; Level 3 changes still always
  need the owner; the platform emergency stop and the per-business stop still work.)
* agent_settings: auto_reply_enabled (default ON), auto_reply_since (only reviews that arrive AFTER this moment are ever answered automatically: switching this on never touches the back
  catalogue), auto_reply_min_rating (4 or 5), auto_reply_daily_limit, reply_templates (the owner's own; empty = the built-in set).
* reply_drafts.auto_published: this reply was approved by the template rule, not by a person (so the history and the screens can say so); template_index: which template was used (so the
  next replies rotate to a different one).

Downgrade removes the new columns, restores autonomy to OFF and the old default; it does not touch replies already published to Google.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_settings", sa.Column("auto_reply_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")))
    op.add_column("agent_settings", sa.Column("auto_reply_since", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")))
    op.add_column("agent_settings", sa.Column("auto_reply_min_rating", sa.SmallInteger(), nullable=False, server_default=sa.text("4")))
    op.add_column("agent_settings", sa.Column("auto_reply_daily_limit", sa.Integer(), nullable=False, server_default=sa.text("30")))
    op.add_column("agent_settings", sa.Column("reply_templates", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.create_check_constraint("ck_agent_settings_auto_reply_rating", "agent_settings", "auto_reply_min_rating in (4, 5)")
    op.execute("ALTER TABLE agent_settings ALTER COLUMN autonomy_enabled SET DEFAULT true")
    op.execute("UPDATE agent_settings SET autonomy_enabled = true")
    op.add_column("reply_drafts", sa.Column("auto_published", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("reply_drafts", sa.Column("template_index", sa.SmallInteger()))


def downgrade() -> None:
    op.drop_column("reply_drafts", "template_index")
    op.drop_column("reply_drafts", "auto_published")
    op.execute("UPDATE agent_settings SET autonomy_enabled = false")
    op.execute("ALTER TABLE agent_settings ALTER COLUMN autonomy_enabled SET DEFAULT false")
    op.drop_constraint("ck_agent_settings_auto_reply_rating", "agent_settings", type_="check")
    for c in ("reply_templates", "auto_reply_daily_limit", "auto_reply_min_rating", "auto_reply_since", "auto_reply_enabled"):
        op.drop_column("agent_settings", c)
