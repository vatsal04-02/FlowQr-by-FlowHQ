"""Agency manager account, part 2: delegate to a FlowQR LocationGroup instead of one person's e-mail (docs/audits/GOOGLE_CLIENT_ACCOUNT_OPTIONS.md section 11).

Revision ID: 0062
Revises: 0061

Additive only, and nothing is on (GOOGLE_AGENCY_MANAGER_ENABLED is off). Migration 0061 could not say WHAT was invited: it had the agency login (`agency_account_id`), the invitation's own name,
the accepted Admin resource and the account the location was later listed under, but not the kind of target, the LocationGroup that was invited, or the account the pending invitation
appeared under. Those are different things and must not be inferred from one another, so each gets its own column:

* google_agency_accounts.location_group_name          the FlowQR LocationGroup this agency login belongs to (`accounts/<id>`), NULL = a login that can only be invited as an individual
* google_agency_authorizations.target_type             individual_agency_user | flowhq_location_group   (existing rows are individual: that is what 0061 did)
* google_agency_authorizations.target_account_name     the LocationGroup that was invited (`accounts/<id>`); required for a group target, forbidden for an individual
* google_agency_authorizations.receiving_account_name  the account under whose invitation list the pending invitation was FOUND (read from Google, never assumed)

Already present from 0061 and used as before: agency_account_id (the agency Google user identity), admin_resource_name (the accepted manager resource),
invitation_name, agency_account_name + verified_at (verified location access).
"""
import sqlalchemy as sa
from alembic import op

revision = "0062"
down_revision = "0061"
branch_labels = None
depends_on = None
GROUP = r"^accounts/[0-9]+$"


def upgrade() -> None:
    op.add_column("google_agency_accounts", sa.Column("location_group_name", sa.String(120)))
    op.create_check_constraint("ck_google_agency_group", "google_agency_accounts", f"location_group_name IS NULL OR location_group_name ~ '{GROUP}'")
    op.add_column("google_agency_authorizations", sa.Column("target_type", sa.String(24), server_default="individual_agency_user", nullable=False))
    op.add_column("google_agency_authorizations", sa.Column("target_account_name", sa.String(120)))
    op.add_column("google_agency_authorizations", sa.Column("receiving_account_name", sa.String(120)))
    op.create_check_constraint("ck_gagency_auth_target_type", "google_agency_authorizations", "target_type IN ('individual_agency_user', 'flowhq_location_group')")
    op.create_check_constraint(
        "ck_gagency_auth_target", "google_agency_authorizations",
        # COALESCE: a CHECK passes when its expression is NULL, so without it a group target with NO group id would slip through.
        f"(target_type = 'flowhq_location_group' AND COALESCE(target_account_name ~ '{GROUP}', false)) OR (target_type = 'individual_agency_user' AND target_account_name IS NULL)")


def downgrade() -> None:
    op.drop_constraint("ck_gagency_auth_target", "google_agency_authorizations", type_="check")
    op.drop_constraint("ck_gagency_auth_target_type", "google_agency_authorizations", type_="check")
    for c in ("receiving_account_name", "target_account_name", "target_type"):
        op.drop_column("google_agency_authorizations", c)
    op.drop_constraint("ck_google_agency_group", "google_agency_accounts", type_="check")
    op.drop_column("google_agency_accounts", "location_group_name")
