"""WhatsApp birthday and festival greetings.

Revision ID: 0053
Revises: 0052

Additive only (plus widening two check constraints). Production must be at 0052 first. Nothing here sends anything: the helpers are off until a business turns them on, and sending stays behind the usual switches.

* whatsapp_contacts.birth_day / birth_month   optional, both or neither, never a year; a day that cannot exist (31 April, 30 February) is refused by the database.
* whatsapp_consents.purpose                   now also allows `occasion`: a separate agreement to birthday and festival greetings.
* whatsapp_templates.category_confirmed       true only once WhatsApp's own status listing has reported the template's category. Until then the category is "not yet known" and the gate treats it as marketing.
* whatsapp_automations.automation_key         now also allows `birthday` and `festival`.
* whatsapp_festivals                          the dated festival list kept by FlowQR staff (name, date, region). Global; rows are never deleted.
* whatsapp_festival_optins                    which festivals a business chose to send greetings for (forced row-level security, the usual tenant policy).
"""
import os

import sqlalchemy as sa
from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
OLD_PURPOSES, NEW_PURPOSES = ("marketing", "utility"), ("marketing", "utility", "occasion")
OLD_KEYS, NEW_KEYS = ("review_followup", "enquiry_followup"), ("review_followup", "enquiry_followup", "birthday", "festival")


def _in(col, values):
    return f"{col} in ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.add_column("whatsapp_contacts", sa.Column("birth_day", sa.SmallInteger()))
    op.add_column("whatsapp_contacts", sa.Column("birth_month", sa.SmallInteger()))
    op.create_check_constraint("ck_wa_contact_birth_pair", "whatsapp_contacts", "(birth_day IS NULL) = (birth_month IS NULL)")
    op.create_check_constraint("ck_wa_contact_birth_valid", "whatsapp_contacts", "birth_month IS NULL OR (birth_month BETWEEN 1 AND 12 AND birth_day BETWEEN 1 AND 31 AND NOT (birth_month IN (4, 6, 9, 11) AND birth_day > 30) AND NOT (birth_month = 2 AND birth_day > 29))")
    op.drop_constraint("ck_wa_consent_purpose", "whatsapp_consents", type_="check")
    op.create_check_constraint("ck_wa_consent_purpose", "whatsapp_consents", _in("purpose", NEW_PURPOSES))
    op.add_column("whatsapp_templates", sa.Column("category_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.drop_constraint("ck_wa_auto_key", "whatsapp_automations", type_="check")
    op.create_check_constraint("ck_wa_auto_key", "whatsapp_automations", _in("automation_key", NEW_KEYS))

    op.create_table(
        "whatsapp_festivals",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("name", sa.String(60), nullable=False), sa.Column("festival_date", sa.Date(), nullable=False),
        sa.Column("region", sa.String(40), nullable=False, server_default="All India"), sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.UUID()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("name", "festival_date", "region", name="uq_wa_festival"),
    )
    op.create_table(
        "whatsapp_festival_optins",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("festival_id", sa.UUID(), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["festival_id"], ["whatsapp_festivals.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "festival_id", name="uq_wa_festival_optin"),
    )
    op.create_index("ix_whatsapp_festival_optins_tenant_id", "whatsapp_festival_optins", ["tenant_id"])
    op.execute("ALTER TABLE whatsapp_festival_optins ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE whatsapp_festival_optins FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON whatsapp_festival_optins USING ({COND}) WITH CHECK ({COND})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON whatsapp_festival_optins TO {APP_ROLE}';
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON whatsapp_festivals TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_table("whatsapp_festival_optins")
    op.drop_table("whatsapp_festivals")
    op.execute("DELETE FROM whatsapp_automation_runs WHERE automation_id IN (SELECT id FROM whatsapp_automations WHERE automation_key IN ('birthday', 'festival'))")
    op.execute("DELETE FROM whatsapp_automations WHERE automation_key IN ('birthday', 'festival')")
    op.drop_constraint("ck_wa_auto_key", "whatsapp_automations", type_="check")
    op.create_check_constraint("ck_wa_auto_key", "whatsapp_automations", _in("automation_key", OLD_KEYS))
    op.drop_column("whatsapp_templates", "category_confirmed")
    op.execute("DELETE FROM whatsapp_consents WHERE purpose = 'occasion'")
    op.drop_constraint("ck_wa_consent_purpose", "whatsapp_consents", type_="check")
    op.create_check_constraint("ck_wa_consent_purpose", "whatsapp_consents", _in("purpose", OLD_PURPOSES))
    op.drop_constraint("ck_wa_contact_birth_valid", "whatsapp_contacts", type_="check")
    op.drop_constraint("ck_wa_contact_birth_pair", "whatsapp_contacts", type_="check")
    op.drop_column("whatsapp_contacts", "birth_month")
    op.drop_column("whatsapp_contacts", "birth_day")
