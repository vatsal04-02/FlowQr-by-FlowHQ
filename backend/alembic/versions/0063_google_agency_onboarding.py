"""Agency onboarding: tenant-safe location mapping, invitation tracking, replay protection (docs/audits/GOOGLE_CLIENT_ACCOUNT_OPTIONS.md section 12).

Revision ID: 0063
Revises: 0062

Additive, nothing is on (GOOGLE_AGENCY_MANAGER_ENABLED and GOOGLE_AGENCY_OPERATIONS_ENABLED are off). Checked against 0061 and 0062 first: neither could say WHICH Google location an authorization is for in a way that is
unique ACROSS businesses (only `google_location_id`, a per-business row), what scope the client chose, when Google was last asked, or which request a consent came from. So:

* google_agency_authorizations.google_location_resource   `locations/<id>` as Google names it, the same for every business. A partial UNIQUE index lets only ONE open authorization exist per Google
                                                           location, so two businesses can never both be mapped to, and managed through, the same location.
* google_agency_authorizations.invite_scope                what the client chose: `location` (one profile) or `business_group` (several profiles of one Google business group)
* google_agency_authorizations.consent_request_id          the client's request id: a replay of the same consent returns what already exists and never starts a second invitation
* google_agency_authorizations.last_polled_at              when Google was last asked about this invitation (polling stays conservative)
* status `withdrawn`                                       the invitation is no longer pending and was never accepted. Google does not say whether the owner withdrew it, FlowQR's group declined it, or it expired, so FlowQR does not claim to
"""
import sqlalchemy as sa
from alembic import op

revision = "0063"
down_revision = "0062"
branch_labels = None
depends_on = None
OPEN_STATES = ("consented", "invited", "accepted", "verified", "active", "needs_attention", "stopping")
OLD_STATES = OPEN_STATES + ("stopped", "lost", "cancelled", "failed")
NEW_STATES = OLD_STATES + ("withdrawn",)


def _in(col, values):
    return f"{col} IN (" + ", ".join(f"'{v}'" for v in values) + ")"


def upgrade() -> None:
    op.add_column("google_agency_authorizations", sa.Column("google_location_resource", sa.String(120)))
    op.add_column("google_agency_authorizations", sa.Column("invite_scope", sa.String(16), server_default="location", nullable=False))
    op.add_column("google_agency_authorizations", sa.Column("consent_request_id", sa.String(64)))
    op.add_column("google_agency_authorizations", sa.Column("last_polled_at", sa.DateTime(timezone=True)))
    # rows written by 0061/0062 get the resource of the Google location they point at
    op.execute("UPDATE google_agency_authorizations a SET google_location_resource = 'locations/' || regexp_replace(g.google_location_name, '^.*/', '') "
               "FROM google_locations g WHERE g.id = a.google_location_id")
    op.create_check_constraint("ck_gagency_auth_scope", "google_agency_authorizations", _in("invite_scope", ("location", "business_group")))
    op.create_index("ix_gagency_auth_request", "google_agency_authorizations", ["tenant_id", "consent_request_id"])
    # ONE open authorization per Google location in the whole platform (an index is not row-level-security bound, which is exactly why it can enforce this across businesses)
    op.create_index("uq_gagency_auth_location_open", "google_agency_authorizations", ["google_location_resource"], unique=True,
                    postgresql_where=sa.text("google_location_resource IS NOT NULL AND status IN (" + ", ".join(f"'{s}'" for s in OPEN_STATES) + ")"))
    op.drop_constraint("ck_google_agency_auth_status", "google_agency_authorizations", type_="check")
    op.create_check_constraint("ck_google_agency_auth_status", "google_agency_authorizations", _in("status", NEW_STATES))


def downgrade() -> None:
    op.execute("UPDATE google_agency_authorizations SET status = 'cancelled' WHERE status = 'withdrawn'")
    op.drop_constraint("ck_google_agency_auth_status", "google_agency_authorizations", type_="check")
    op.create_check_constraint("ck_google_agency_auth_status", "google_agency_authorizations", _in("status", OLD_STATES))
    op.drop_index("uq_gagency_auth_location_open", table_name="google_agency_authorizations")
    op.drop_index("ix_gagency_auth_request", table_name="google_agency_authorizations")
    op.drop_constraint("ck_gagency_auth_scope", "google_agency_authorizations", type_="check")
    for c in ("last_polled_at", "consent_request_id", "invite_scope", "google_location_resource"):
        op.drop_column("google_agency_authorizations", c)
