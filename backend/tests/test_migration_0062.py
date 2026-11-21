"""Migration 0062 (agency LocationGroup target): additive, constrained, reversible, and every existing row keeps meaning what it meant."""
import pytest
from sqlalchemy.exc import IntegrityError

from tests.conftest import make_business, owner_exec, owner_query
from tests.test_migration_0037 import alembic


def cols(table):
    return {r[0] for r in owner_query("SELECT column_name FROM information_schema.columns WHERE table_name = :t", t=table)}


def test_new_columns_and_checks_exist():
    assert "location_group_name" in cols("google_agency_accounts")
    assert {"target_type", "target_account_name", "receiving_account_name"} <= cols("google_agency_authorizations")
    cons = {r[0] for r in owner_query("SELECT conname FROM pg_constraint WHERE conrelid = 'google_agency_authorizations'::regclass")}
    assert {"ck_gagency_auth_target_type", "ck_gagency_auth_target"} <= cons
    assert "ck_google_agency_group" in {r[0] for r in owner_query("SELECT conname FROM pg_constraint WHERE conrelid = 'google_agency_accounts'::regclass")}


def _seed_auth(target_type, target_account, name_the_target=True):
    biz = make_business()
    owner_exec("INSERT INTO google_connections (id, tenant_id, status, api_access, auth_mode) VALUES (gen_random_uuid(), :t, 'active', 'approved', 'client_token')", t=biz.tenant_id)
    cid = owner_query("SELECT id FROM google_connections WHERE tenant_id = :t", t=biz.tenant_id)[0][0]
    owner_exec("INSERT INTO google_locations (id, tenant_id, connection_id, google_account_name, google_location_name, selected, consecutive_failures) VALUES (gen_random_uuid(), :t, :c, 'accounts/1', 'locations/1', true, 0)", t=biz.tenant_id, c=str(cid))
    gid = owner_query("SELECT id FROM google_locations WHERE tenant_id = :t", t=biz.tenant_id)[0][0]
    if name_the_target:
        owner_exec("INSERT INTO google_agency_authorizations (id, tenant_id, connection_id, google_location_id, consent_version, consent_text_sha256, consented_at, target_type, target_account_name) "
                   "VALUES (gen_random_uuid(), :t, :c, :g, 'v', 'h', now(), :tt, :ta)", t=biz.tenant_id, c=str(cid), g=str(gid), tt=target_type, ta=target_account)
    else:  # exactly how migration 0061 wrote a row: no target named
        owner_exec("INSERT INTO google_agency_authorizations (id, tenant_id, connection_id, google_location_id, consent_version, consent_text_sha256, consented_at) "
                   "VALUES (gen_random_uuid(), :t, :c, :g, 'v', 'h', now())", t=biz.tenant_id, c=str(cid), g=str(gid))
    return biz.tenant_id


def test_a_group_authorization_needs_a_numeric_group_and_an_individual_must_not_carry_one():
    _seed_auth("flowhq_location_group", "accounts/5488245563")
    _seed_auth("individual_agency_user", None)
    for tt, ta in (("flowhq_location_group", None), ("flowhq_location_group", "agency@flowqr.test"), ("flowhq_location_group", "accounts/abc"),
                   ("individual_agency_user", "accounts/5488245563"), ("something_else", None)):
        with pytest.raises(IntegrityError):
            _seed_auth(tt, ta)


def test_a_login_can_only_record_a_numeric_group():
    owner_exec("DELETE FROM google_agency_accounts WHERE label = 'mig0062'")
    owner_exec("INSERT INTO google_agency_accounts (id, label, google_email, location_group_name) VALUES (gen_random_uuid(), 'mig0062', 'mig0062@flowqr.test', 'accounts/5488245563')")
    with pytest.raises(IntegrityError):
        owner_exec("INSERT INTO google_agency_accounts (id, label, google_email, location_group_name) VALUES (gen_random_uuid(), 'mig0062b', 'mig0062b@flowqr.test', 'not-a-group')")
    owner_exec("DELETE FROM google_agency_accounts WHERE label = 'mig0062'")


def test_existing_authorizations_stay_individual_and_the_downgrade_round_trips():
    tenant = _seed_auth(None, None, name_the_target=False)  # a row written the 0061 way names no target
    assert owner_query("SELECT target_type, target_account_name FROM google_agency_authorizations WHERE tenant_id = :t", t=tenant)[0] == ("individual_agency_user", None)
    owner_exec("DELETE FROM google_agency_authorizations")
    alembic("downgrade", "0061")
    try:
        assert not ({"target_type", "target_account_name", "receiving_account_name"} & cols("google_agency_authorizations"))
        assert "location_group_name" not in cols("google_agency_accounts")
        assert "agency_account_name" in cols("google_agency_authorizations")  # 0061 is untouched
    finally:
        alembic("upgrade", "head")
    assert owner_query("SELECT version_num FROM alembic_version")[0][0] == "0063"
