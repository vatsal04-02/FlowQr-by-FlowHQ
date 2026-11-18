"""Consent grants: automation is opt-in, per location and per action type (Local SEO Milestone 2, decisions D2).

Revision ID: 0038
Revises: 0037

* New tenant table `consent_grants` (RLS forced, same tenant policy as every tenant table). One row = one owner's express consent for ONE action type at ONE location, with the
  exact wording shown, who agreed and when, and (when withdrawn) who withdrew it and when. Rows are append-only in spirit: a trigger refuses DELETE (except the whole-business
  erase that the retention/offboarding jobs already use, flag `app.history_purge`) and refuses any UPDATE except recording the revocation of a grant that is still active.
* `agent_settings.autonomy_enabled` and `auto_reply_enabled` become OFF by default (they were ON by default since 0031, owner decision 2026-11-15; overridden by decision D2 of
  2026-11-17: Google requires "prior specific and express consent"). Existing rows are switched OFF too: nobody silently inherits automation, and nothing has to be
  re-granted for work that needs a person anyway. An owner turns it back on deliberately and grants each location and action type.
Downgrade drops the table and restores the previous column defaults; it does NOT switch anybody's automation back on (that would be a new consent decision made for them).
Chain: 0036 (production's former head) -> 0037 (Cashfree) -> 0038.
"""
import os

from alembic import op
import sqlalchemy as sa

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "consent_grants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("google_location_id", sa.UUID(), nullable=False),
        sa.Column("scope", sa.String(40), nullable=False),
        sa.Column("wording_version", sa.String(24), nullable=False),
        sa.Column("wording_text", sa.Text(), nullable=False),
        sa.Column("granted_by", sa.UUID()),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("source", sa.String(16), nullable=False, server_default="owner_ui"),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_by", sa.UUID()),
        sa.Column("revoked_reason", sa.Text()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["google_location_id"], ["google_locations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["revoked_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("uq_consent_active", "consent_grants", ["google_location_id", "scope"], unique=True, postgresql_where=sa.text("revoked_at is null"))
    op.create_index("ix_consent_tenant", "consent_grants", ["tenant_id", "granted_at"])
    op.execute("ALTER TABLE consent_grants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE consent_grants FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON consent_grants USING ({COND}) WITH CHECK ({COND})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE ON consent_grants TO {APP_ROLE}';
          END IF;
        END $$;
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION consent_grants_guard() RETURNS trigger AS $$
        BEGIN
          IF TG_OP = 'DELETE' THEN
            IF current_setting('app.history_purge', true) = 'on' THEN
              RETURN OLD;  -- only the erasure of a whole business may remove its consent history
            END IF;
            RAISE EXCEPTION 'consent_grants is a record of consent: DELETE refused' USING ERRCODE = '42501';
          END IF;
          IF OLD.revoked_at IS NOT NULL THEN
            RAISE EXCEPTION 'a revoked consent grant cannot be changed' USING ERRCODE = '42501';
          END IF;
          IF NEW.id IS DISTINCT FROM OLD.id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id OR NEW.google_location_id IS DISTINCT FROM OLD.google_location_id
             OR NEW.scope IS DISTINCT FROM OLD.scope OR NEW.wording_version IS DISTINCT FROM OLD.wording_version OR NEW.wording_text IS DISTINCT FROM OLD.wording_text
             OR NEW.granted_by IS DISTINCT FROM OLD.granted_by OR NEW.granted_at IS DISTINCT FROM OLD.granted_at OR NEW.source IS DISTINCT FROM OLD.source THEN
            RAISE EXCEPTION 'a consent grant can only be revoked, never edited' USING ERRCODE = '42501';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("CREATE TRIGGER consent_grants_no_edit BEFORE UPDATE OR DELETE ON consent_grants FOR EACH ROW EXECUTE FUNCTION consent_grants_guard()")

    op.alter_column("agent_settings", "autonomy_enabled", server_default=sa.text("false"))
    op.alter_column("agent_settings", "auto_reply_enabled", server_default=sa.text("false"))
    op.execute("SELECT set_config('app.bypass_rls', 'on', true)")
    op.execute("UPDATE agent_settings SET autonomy_enabled = false, auto_reply_enabled = false WHERE autonomy_enabled OR auto_reply_enabled")


def downgrade() -> None:
    op.alter_column("agent_settings", "autonomy_enabled", server_default=sa.text("true"))
    op.alter_column("agent_settings", "auto_reply_enabled", server_default=sa.text("true"))
    op.execute("SELECT set_config('app.history_purge', 'on', true)")
    op.execute("DROP TRIGGER IF EXISTS consent_grants_no_edit ON consent_grants")
    op.execute("DROP FUNCTION IF EXISTS consent_grants_guard()")
    op.drop_table("consent_grants")
