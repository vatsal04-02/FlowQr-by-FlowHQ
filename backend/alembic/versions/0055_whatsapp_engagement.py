"""WhatsApp engagement and win-back: three timestamps on a customer.

Revision ID: 0055
Revises: 0054

Additive only. Production must be at 0054 first. Nothing here sends anything.

* whatsapp_contacts.last_replied_at   when the customer last wrote to the business. A time only: no message text is stored. A STOP never sets it.
* whatsapp_contacts.last_visit_at     when the owner last marked a visit as done (recorded even when no helper is on).
* whatsapp_contacts.last_enquiry_at   when the customer last sent a website enquiry that came with a WhatsApp agreement.
They are columns of the customer, so they are exported with the customer and deleted with the customer and with the business. Engagement choices (read, replied, clicked, delivered but not read, no
engagement in the last N offers) and win-back use these and the existing message and click records; no other table changes.
"""
import sqlalchemy as sa
from alembic import op

revision = "0055"
down_revision = "0054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for col in ("last_replied_at", "last_visit_at", "last_enquiry_at"):
        op.add_column("whatsapp_contacts", sa.Column(col, sa.DateTime(timezone=True)))


def downgrade() -> None:
    for col in ("last_enquiry_at", "last_visit_at", "last_replied_at"):
        op.drop_column("whatsapp_contacts", col)
