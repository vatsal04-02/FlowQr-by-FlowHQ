"""WhatsApp campaign manager (Phase 4): a customer's location, and a flag marking which approved templates are simple enough to send with plain text variables.

Revision ID: 0050
Revises: 0049

Additive only: two nullable-or-defaulted columns on existing WhatsApp tables. Production must be at 0049 first.

* whatsapp_contacts.location_id    optional: which of the business's locations a customer belongs to (location-specific offers). SET NULL if the location is deleted.
* whatsapp_templates.simple        true when the approved template has only a text body (no header, media or button variables), so a campaign can fill it with plain text. Existing rows are the
                                   FlowQR standard templates, which are simple.
"""
import sqlalchemy as sa
from alembic import op

revision = "0050"
down_revision = "0049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("whatsapp_contacts", sa.Column("location_id", sa.UUID()))
    op.create_foreign_key("fk_wa_contact_location", "whatsapp_contacts", "locations", ["location_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_wa_contact_location", "whatsapp_contacts", ["tenant_id", "location_id"])
    op.add_column("whatsapp_templates", sa.Column("simple", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("whatsapp_templates", "simple")
    op.drop_index("ix_wa_contact_location", "whatsapp_contacts")
    op.drop_constraint("fk_wa_contact_location", "whatsapp_contacts", type_="foreignkey")
    op.drop_column("whatsapp_contacts", "location_id")
