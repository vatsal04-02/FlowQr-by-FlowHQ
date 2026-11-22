"""Migration 0063 (agency onboarding): tenant-safe location mapping, replay protection, the withdrawn status. Additive, reversible, existing rows keep their meaning."""
import pytest
from sqlalchemy.exc import IntegrityError

from tests.conftest import owner_exec, owner_query
from tests.test_migration_0037 import alembic
from tests.test_migration_0062 import _seed_auth, cols


def test_new_columns_checks_and_the_platform_wide_index_exist():
    assert {"google_location_resource", "invite_scope", "consent_request_id", "last_polled_at"} <= cols("google_agency_authorizations")
    cons = {r[0] for r in owner_query("SELECT conname FROM pg_constraint WHERE conrelid = 'google_agency_authorizations'::regclass")}
    assert {"ck_gagency_auth_scope", "ck_google_agency_auth_status"} <= cons
    (ix,) = owner_query("SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_gagency_auth_location_open'")[0]
    assert "UNIQUE" in ix and "google_location_resource" in ix and "status" in ix  # unique on the resource alone, for OPEN statuses only


def test_withdrawn_is_a_real_status_and_an_unknown_scope_or_status_is_refused():
    tenant = _seed_auth("individual_agency_user", None)
    owner_exec("UPDATE google_agency_authorizations SET status = 'withdrawn' WHERE tenant_id = :t", t=tenant)
    for sql in ("UPDATE google_agency_authorizations SET invite_scope = 'everything' WHERE tenant_id = :t", "UPDATE google_agency_authorizations SET status = 'rejected' WHERE tenant_id = :t"):
        with pytest.raises(IntegrityError):
            owner_exec(sql, t=tenant)
    owner_exec("DELETE FROM google_agency_authorizations")


def test_only_one_open_authorization_can_exist_per_google_location_across_businesses_and_closed_ones_free_it():
    t1, t2 = _seed_auth("individual_agency_user", None), _seed_auth("individual_agency_user", None)
    owner_exec("UPDATE google_agency_authorizations SET google_location_resource = 'locations/9' WHERE tenant_id = :t", t=t1)
    with pytest.raises(IntegrityError):
        owner_exec("UPDATE google_agency_authorizations SET google_location_resource = 'locations/9' WHERE tenant_id = :t", t=t2)  # a different business, the same Google location
    owner_exec("UPDATE google_agency_authorizations SET status = 'stopped' WHERE tenant_id = :t", t=t1)
    owner_exec("UPDATE google_agency_authorizations SET google_location_resource = 'locations/9' WHERE tenant_id = :t", t=t2)  # the first one ended: the location is free
    owner_exec("DELETE FROM google_agency_authorizations")


def test_existing_rows_get_their_locations_resource_and_the_downgrade_round_trips():
    tenant = _seed_auth("individual_agency_user", None)  # written without a resource, the way 0062 wrote rows
    owner_exec("UPDATE google_agency_authorizations SET status = 'withdrawn' WHERE tenant_id = :t", t=tenant)
    alembic("downgrade", "0062")
    try:
        assert not ({"google_location_resource", "invite_scope", "consent_request_id", "last_polled_at"} & cols("google_agency_authorizations"))
        assert owner_query("SELECT status FROM google_agency_authorizations WHERE tenant_id = :t", t=tenant)[0][0] == "cancelled"  # 'withdrawn' did not exist before 0063
    finally:
        alembic("upgrade", "head")
    assert owner_query("SELECT google_location_resource, invite_scope FROM google_agency_authorizations WHERE tenant_id = :t", t=tenant)[0] == ("locations/1", "location")  # backfilled from the location it points at
    assert owner_query("SELECT version_num FROM alembic_version")[0][0] == "0066"
    owner_exec("DELETE FROM google_agency_authorizations")
