"""Agency manager account for Google Business Profile (docs/audits/GOOGLE_CLIENT_ACCOUNT_OPTIONS.md, Option B).

Revision ID: 0061
Revises: 0060

Additive only. Production must be at 0060 first. Nothing here is on: the switch GOOGLE_AGENCY_MANAGER_ENABLED is off, every existing connection stays `client_token`, and no existing row changes meaning.

* google_agency_accounts        PLATFORM-ONLY (row-level security admits the bypass context and nothing else). The FlowQR agency Google logins. Tokens are encrypted with their OWN key
                                (AGENCY_TOKEN_ENCRYPTION_KEY), never the key that protects client tokens.
* google_agency_authorizations  per client location: the stored consent, and every date in the invite, accept, notice, removal story. Tenant-isolated. Holds NO Google content (no reviews, replies,
                                posts, photos or metrics) and no token, so the 30-day storage rule has nothing to apply to here.
* google_connections            + auth_mode (client_token | agency_account), agency_account_id, agency_switched_at
* google_locations              + client_google_account_name: the account name the client's own login saw, kept when the location is switched to the account the agency login sees.
"""
import os

import sqlalchemy as sa
from alembic import op

revision = "0061"
down_revision = "0060"
branch_labels = None
depends_on = None
APP_ROLE = os.environ.get("APP_DB_ROLE", "flowqr_app")
COND = "current_setting('app.bypass_rls', true) = 'on' OR tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid"
PLATFORM_ONLY = "current_setting('app.bypass_rls', true) = 'on'"
OPEN_STATES = ("consented", "invited", "accepted", "verified", "active", "needs_attention", "stopping")
STATES = OPEN_STATES + ("stopped", "lost", "cancelled", "failed")


def _in(col, values):
    return f"{col} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.create_table(
        "google_agency_accounts",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("label", sa.String(80), nullable=False), sa.Column("google_email", sa.String(254), nullable=False),
        sa.Column("google_sub", sa.String(64)), sa.Column("refresh_token_encrypted", sa.Text()), sa.Column("access_token_encrypted", sa.Text()),
        sa.Column("access_token_expires_at", sa.DateTime(timezone=True)), sa.Column("status", sa.String(12), server_default="active", nullable=False),
        sa.Column("max_locations", sa.Integer()), sa.Column("last_error", sa.String(300)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"), sa.UniqueConstraint("label", name="uq_google_agency_label"), sa.UniqueConstraint("google_email", name="uq_google_agency_email"),
        sa.CheckConstraint(_in("status", ("active", "disabled", "revoked")), name="ck_google_agency_status"),
        sa.CheckConstraint("max_locations IS NULL OR max_locations > 0", name="ck_google_agency_max"),
    )

    op.add_column("google_connections", sa.Column("auth_mode", sa.String(16), server_default="client_token", nullable=False))
    op.add_column("google_connections", sa.Column("agency_account_id", sa.UUID()))
    op.add_column("google_connections", sa.Column("agency_switched_at", sa.DateTime(timezone=True)))
    op.create_foreign_key("fk_gconn_agency_account", "google_connections", "google_agency_accounts", ["agency_account_id"], ["id"], ondelete="RESTRICT")
    op.create_check_constraint("ck_gconn_auth_mode", "google_connections", _in("auth_mode", ("client_token", "agency_account")))
    op.create_check_constraint("ck_gconn_agency_account", "google_connections", "auth_mode <> 'agency_account' OR agency_account_id IS NOT NULL")
    op.add_column("google_locations", sa.Column("client_google_account_name", sa.String(120)))

    op.create_table(
        "google_agency_authorizations",
        sa.Column("id", sa.UUID(), nullable=False), sa.Column("tenant_id", sa.UUID(), nullable=False), sa.Column("connection_id", sa.UUID(), nullable=False),
        sa.Column("google_location_id", sa.UUID(), nullable=False), sa.Column("agency_account_id", sa.UUID()),
        sa.Column("status", sa.String(16), server_default="consented", nullable=False),
        # who agreed to what, and when
        sa.Column("consent_version", sa.String(40), nullable=False), sa.Column("consent_text_sha256", sa.String(64), nullable=False), sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consented_by", sa.UUID()), sa.Column("consented_by_email", sa.String(254)),
        # invite, accept, visibility, switch
        sa.Column("admin_resource_name", sa.String(200)), sa.Column("invitation_name", sa.String(200)), sa.Column("agency_account_name", sa.String(120)),
        sa.Column("invite_sent_at", sa.DateTime(timezone=True)), sa.Column("accepted_at", sa.DateTime(timezone=True)), sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.Column("switched_at", sa.DateTime(timezone=True)), sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("client_token_revoked_at", sa.DateTime(timezone=True)), sa.Column("client_token_revoke_attempts", sa.Integer(), server_default="0", nullable=False),
        # the separate notice to the client (Google policy: within 48 hours of FlowQR becoming a manager)
        sa.Column("notice_due_at", sa.DateTime(timezone=True)), sa.Column("notice_sent_at", sa.DateTime(timezone=True)), sa.Column("notice_overdue_alerted_at", sa.DateTime(timezone=True)),
        # stopping, and losing access
        sa.Column("removal_requested_at", sa.DateTime(timezone=True)), sa.Column("removal_requested_by", sa.UUID()), sa.Column("removal_deadline_at", sa.DateTime(timezone=True)),
        sa.Column("removal_alerted_at", sa.DateTime(timezone=True)), sa.Column("removed_at", sa.DateTime(timezone=True)), sa.Column("lost_at", sa.DateTime(timezone=True)),
        sa.Column("failure_code", sa.String(40)), sa.Column("last_error", sa.String(300)), sa.Column("attempts", sa.Integer(), server_default="0", nullable=False), sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["connection_id"], ["google_connections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["google_location_id"], ["google_locations.id"], ondelete="CASCADE"), sa.ForeignKeyConstraint(["agency_account_id"], ["google_agency_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["consented_by"], ["users.id"], ondelete="SET NULL"), sa.ForeignKeyConstraint(["removal_requested_by"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(_in("status", STATES), name="ck_google_agency_auth_status"),
    )
    op.create_index("ix_google_agency_authorizations_tenant_id", "google_agency_authorizations", ["tenant_id"])
    op.create_index("ix_gagency_auth_connection", "google_agency_authorizations", ["connection_id"])
    # one live authorization per Google location: a second consent while one is open reuses it (and a duplicate invite can never start from here)
    op.create_index("uq_gagency_auth_open", "google_agency_authorizations", ["google_location_id"], unique=True,
                    postgresql_where=sa.text("status IN (" + ", ".join(f"'{s}'" for s in OPEN_STATES) + ")"))

    for t, cond in (("google_agency_authorizations", COND),):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY tenant_isolation ON {t} USING ({cond}) WITH CHECK ({cond})")
    op.execute("ALTER TABLE google_agency_accounts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE google_agency_accounts FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY platform_only ON google_agency_accounts USING ({PLATFORM_ONLY}) WITH CHECK ({PLATFORM_ONLY})")
    op.execute(f"""
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON google_agency_accounts, google_agency_authorizations TO {APP_ROLE}';
          END IF;
        END $$;
    """)


def downgrade() -> None:
    op.drop_table("google_agency_authorizations")
    op.drop_column("google_locations", "client_google_account_name")
    op.drop_constraint("ck_gconn_agency_account", "google_connections", type_="check")
    op.drop_constraint("ck_gconn_auth_mode", "google_connections", type_="check")
    op.drop_constraint("fk_gconn_agency_account", "google_connections", type_="foreignkey")
    for c in ("agency_switched_at", "agency_account_id", "auth_mode"):
        op.drop_column("google_connections", c)
    op.drop_table("google_agency_accounts")
