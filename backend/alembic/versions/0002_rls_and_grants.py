"""Row-Level Security policies and least-privilege grants for the app role.

Revision ID: 0002
Revises: 0001
"""
import os

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")

TENANT_TABLES = [
    "memberships", "invitations", "locations", "google_connections", "google_locations", "reviews",
    "reply_drafts", "reply_logs", "qr_cards", "card_assignments", "scan_events", "ai_generation_logs",
    "subscriptions", "audit_logs",
]

CONDITION = (
    "current_setting('app.bypass_rls', true) = 'on' "
    "OR {col} = nullif(current_setting('app.tenant_id', true), '')::uuid"
)


def upgrade() -> None:
    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        cond = CONDITION.format(col="tenant_id")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({cond}) WITH CHECK ({cond})")
    # tenants: a row is visible only to its own tenant context.
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    cond = CONDITION.format(col="id")
    op.execute(f"CREATE POLICY tenant_isolation ON tenants USING ({cond}) WITH CHECK ({cond})")

    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT USAGE ON SCHEMA public TO {APP_ROLE}';
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE}';
            EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}';
            EXECUTE 'REVOKE ALL ON alembic_version FROM {APP_ROLE}';
            -- audit trail is append-only for the application
            EXECUTE 'REVOKE UPDATE, DELETE ON audit_logs FROM {APP_ROLE}';
            EXECUTE 'REVOKE UPDATE, DELETE ON reply_logs FROM {APP_ROLE}';
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    for table in TENANT_TABLES + ["tenants"]:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
