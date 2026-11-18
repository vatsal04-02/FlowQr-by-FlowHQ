"""Privacy and account lifecycle: age declaration, deleting one's own account, retention of IP addresses and demo requests.

Revision ID: 0045
Revises: 0044

* `users`: `age_confirmed_at` / `age_declaration_version` (the 18+ declaration made at sign-up; NULL for everyone who registered before it existed, nobody's status is guessed) and the
  self-deletion state (`deletion_requested_at`, hash and expiry of the emailed single-use confirm link, `deletion_confirmed_at`, `deletion_scheduled_for`, `deleted_at`).
* `leads`: the application role could only SELECT and INSERT (0019). Retention of demo requests needs DELETE, granted here and nowhere wider.
* `audit_logs` stays append-only for everything that matters, but its IP address can now be removed on a schedule (and when a person deletes their account). The application role gets
  UPDATE on the `ip` column ONLY (a column-level grant), and a trigger refuses any update that changes anything except setting `ip` to NULL (or the database's own ON DELETE SET NULL of
  `tenant_id` / `user_id`, which must keep working). So the content of an audit entry still cannot be edited, even by the table owner.
Chain: ... -> 0043 (user picture) -> 0044 (consent) -> 0045. (Written as 0039 before it joined the release chain; renumbered so it cannot collide with the unreleased cardless-trial branch's 0039.)
Downgrade removes the guard, the grants and the columns (losing the declarations and any pending self-deletions); it restores nothing that retention already erased.
"""
import os

from alembic import op
import sqlalchemy as sa

revision = "0045"
down_revision = "0044"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")


def upgrade() -> None:
    for name, typ in (("age_confirmed_at", sa.DateTime(timezone=True)), ("age_declaration_version", sa.String(24)), ("deletion_requested_at", sa.DateTime(timezone=True)),
                      ("deletion_token_hash", sa.String(64)), ("deletion_token_expires_at", sa.DateTime(timezone=True)), ("deletion_confirmed_at", sa.DateTime(timezone=True)),
                      ("deletion_scheduled_for", sa.DateTime(timezone=True)), ("deleted_at", sa.DateTime(timezone=True))):
        op.add_column("users", sa.Column(name, typ))
    op.create_index("ix_users_deletion_scheduled", "users", ["deletion_scheduled_for"], postgresql_where=sa.text("deletion_scheduled_for is not null and deleted_at is null"))
    op.create_index("ix_users_deletion_token", "users", ["deletion_token_hash"], postgresql_where=sa.text("deletion_token_hash is not null"))

    op.execute("""
        CREATE OR REPLACE FUNCTION audit_logs_ip_only() RETURNS trigger AS $$
        BEGIN
          IF (to_jsonb(NEW) - 'ip' - 'tenant_id' - 'user_id') IS DISTINCT FROM (to_jsonb(OLD) - 'ip' - 'tenant_id' - 'user_id') THEN
            RAISE EXCEPTION 'audit_logs is append-only: only the IP address may be removed' USING ERRCODE = '42501';
          END IF;
          IF NEW.ip IS NOT NULL AND NEW.ip IS DISTINCT FROM OLD.ip THEN
            RAISE EXCEPTION 'audit_logs: an IP address can be removed, never changed' USING ERRCODE = '42501';
          END IF;
          IF (NEW.tenant_id IS NOT NULL AND NEW.tenant_id IS DISTINCT FROM OLD.tenant_id) OR (NEW.user_id IS NOT NULL AND NEW.user_id IS DISTINCT FROM OLD.user_id) THEN
            RAISE EXCEPTION 'audit_logs: the tenant and user can only be cleared, never changed' USING ERRCODE = '42501';
          END IF;
          RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("CREATE TRIGGER audit_logs_ip_only_guard BEFORE UPDATE ON audit_logs FOR EACH ROW EXECUTE FUNCTION audit_logs_ip_only()")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT UPDATE (ip) ON audit_logs TO {APP_ROLE}';
            EXECUTE 'GRANT DELETE ON leads TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'REVOKE UPDATE (ip) ON audit_logs FROM {APP_ROLE}';
            EXECUTE 'REVOKE DELETE ON leads FROM {APP_ROLE}';
          END IF;
        END $$;
    """)
    op.execute("DROP TRIGGER IF EXISTS audit_logs_ip_only_guard ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS audit_logs_ip_only()")
    op.drop_index("ix_users_deletion_token", table_name="users")
    op.drop_index("ix_users_deletion_scheduled", table_name="users")
    for name in ("deleted_at", "deletion_scheduled_for", "deletion_confirmed_at", "deletion_token_expires_at", "deletion_token_hash", "deletion_requested_at",
                 "age_declaration_version", "age_confirmed_at"):
        op.drop_column("users", name)
