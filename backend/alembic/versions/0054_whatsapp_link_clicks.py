"""WhatsApp click tracking (Pro): tracked review links and the clicks on them.

Revision ID: 0054
Revises: 0053

Additive only. Production must be at 0053 first. Nothing here sends anything or changes any existing behaviour: a business turns link counting on for the review request, on the Pro add-on.

* whatsapp_links         a long random token that always leads to one FIXED destination (the business's own review page). Belongs to the business (deleted with it); the message and the customer it was sent
                         to are nullable references, so deleting either does not break the link for someone who still holds it.
* whatsapp_link_clicks   one row per counted click: link, customer, message, time. No address, no browser, no place. Deleted with the customer and with the business.
Both have forced row-level security with the usual tenant policy. The public redirect looks a link up by its token, like the QR card redirect does.
"""
import os

import sqlalchemy as sa
from alembic import op

revision = "0054"
down_revision = "0053"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "whatsapp_links",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("token", sa.String(64), nullable=False), sa.Column("destination", sa.String(500), nullable=False),
        sa.Column("idem_key", sa.String(200)), sa.Column("message_id", sa.UUID()), sa.Column("contact_id", sa.UUID()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["message_id"], ["whatsapp_messages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["contact_id"], ["whatsapp_contacts.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("token", name="uq_wa_link_token"), sa.UniqueConstraint("tenant_id", "idem_key", name="uq_wa_link_idem"),
    )
    op.create_index("ix_whatsapp_links_tenant_id", "whatsapp_links", ["tenant_id"])
    op.create_table(
        "whatsapp_link_clicks",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("link_id", sa.UUID(), nullable=False), sa.Column("contact_id", sa.UUID()), sa.Column("message_id", sa.UUID()),
        sa.Column("clicked_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["link_id"], ["whatsapp_links.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["whatsapp_contacts.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["message_id"], ["whatsapp_messages.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_wa_click_link_time", "whatsapp_link_clicks", ["link_id", "clicked_at"])
    op.create_index("ix_wa_click_tenant_time", "whatsapp_link_clicks", ["tenant_id", "clicked_at"])
    for t in ("whatsapp_links", "whatsapp_link_clicks"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({COND}) WITH CHECK ({COND})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON whatsapp_links, whatsapp_link_clicks TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_table("whatsapp_link_clicks")
    op.drop_table("whatsapp_links")
